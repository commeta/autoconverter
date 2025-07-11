#!/usr/bin/env python3
#
# Usage:
#   autoconverter.py [-h] [-s STOP] [-b BACKGROUND]
#
# Blocks monitoring |path| and its subdirectories for modifications on
# files ending with suffix |*.jpg,*.png|. Run |cwebp| each time a modification
# is detected. 
#
#
# Dependencies:
#   Linux, Python >= 3.5, Pyinotify, Webptools
#
# http://seb.dbzteam.org/pyinotify/
# https://github.com/seb-m/pyinotify
# https://github.com/scionoftech/webptools
# https://docs.python.org/2/library/multiprocessing.html
# https://www.ibm.com/developerworks/ru/library/l-inotify/
# https://mnorin.com/inotify-v-bash.html
#
# yum install python-inotify.noarch python-inotify-examples.noarch 
# apt install python3-pyinotify 



from ctypes import cdll
from webptools import webplib as webp
from pathlib import Path

import pyinotify
import multiprocessing
import time
import sys
import argparse
import os
import signal
import shutil


class Ev(object): # Event struct
    mask = ""
    pathname = ""
    dir = False
    wait = False


class OnWriteHandler(pyinotify.ProcessEvent):
    # Создание очередей, слушатель inotify ядра
    def my_init(self, path, extension, queue_in):
        self.path = path
        self.extensions = extension.split(',')
        self.queue_in = queue_in

    def process_IN_CLOSE_WRITE(self, event):
        # Были закрыты файл или директория, открытые ранее на запись. 
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions):
            return
        if event.dir == True:
            return
        event.mask = "IN_CLOSE_WRITE"
        queue_in.put(event)  # добавляем элемент в очередь модификации

    def process_IN_DELETE(self, event):
        # В наблюдаемой директории были удалены файл или поддиректория.
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions):
            return
        if event.dir == True:
            return
        event.mask = "IN_DELETE"
        queue_in.put(event)  # добавляем элемент в очередь удаления

    def process_IN_MOVED_TO(self, event):
        # Файл или директория были перемещены в наблюдаемую директорию. 
        # Событие включает в себя cookie, как и событие IN_MOVED_FROM. 
        # Если файл или директория просто переименовать, то произойдут оба события. 
        # Если объект перемещается в/из директории, за которой не установлено наблюдение, мы увидим только одно событие. 
        # При перемещении или переименовании объекта наблюдение за ним продолжается.
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions) and event.dir == False:
            return
        event.mask = "IN_MOVED_TO"
        # добавляем элемент в очередь, модификация или переименование
        queue_in.put(event)

    def process_IN_MOVED_FROM(self, event):
        # Наблюдаемый объект или элемент в наблюдаемой директории был перемещен из места наблюдения. 
        # Событие включает в себя cookie, по которому его можно сопоставить с событием IN_MOVED_TO.
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions) and event.dir == False:
            return
        event.mask = "IN_MOVED_FROM"
        event.wait = True
        # добавляем элемент в очередь, удаление или переименование
        queue_in.put(event)


def converter(queue_in, path): # Обработчик очереди в отдельном процессе
    # Смена приоритета
    pid = libc.getpid()
    libc.setpriority(0, pid, 20)

    filter = {}
    moved = {}

    while True:
        event = queue_in.get()  # Извлекаем элемент из очереди
        mask = event.mask
        is_dir = event.dir
        item = event.pathname
        
        if mask == "SIG_TERM":
            break


        # Удалим из фильтра события старше 2-х секунд
        for key, value in list(filter.items()):
            if value['time'] + 2 < time.time():
                del filter[key]


        for p in path:
            if (item + "/").startswith(p + "/"):
                #Init
                extension = Path(item).suffix.lower()
                dest = p + result_path
                dest_item = item.replace(p, dest)
                base_dest_item = Path(dest_item).parent
                base_item = Path(item).parent

                uid = os.stat(p).st_uid
                gid = os.stat(p).st_gid


                if not Path(dest).is_dir():  # создает каталог если нету /webp
                    Path(dest).mkdir(parents=True, exist_ok=True)
                    os.chown(dest, uid, gid)


                if item.startswith(dest):  # если это /webp то выход
                    break
                

                if mask == "IN_MOVED_FROM": # Перемещение файла или каталога
                    if event.wait == False:
                        if item in moved:  # Внутреннее - переименовываем
                            # Проверить перемещение из разных точек наблюдения
                            moved_dest_item = moved[item].replace(p, dest)
                            log(p, "Rename: " + dest_item,
                                mask="IN_MOVED_FROM Rename")
                            Path(dest_item).rename(moved_dest_item)
                            del moved[item]
                            break
                            
                        else: # Внешнее - удаляем
                            log(p, "Delete: " + dest_item,
                                mask="IN_MOVED_FROM Delete")
                            if Path(dest_item).is_file():
                                Path(dest_item).unlink()
                                rm_empty_dir(base_dest_item)
                            else:
                                rm_tree(dest_item)
                            break

                    if event.wait == True:  # Чтобы понять направление подождем IN_MOVED_TO
                        event.wait = False
                        queue_in.put(event)
                        break


                if mask == "IN_DELETE" and Path(dest_item).is_file():
                    log(p, "Delete: " + dest_item, mask="IN_DELETE Delete")
                    Path(dest_item).unlink()  # Удаляем файл

                    # Удаляем подкаталог если пустой
                    if rm_empty_dir(base_dest_item):
                        log(p, "Delete dir: " +
                            str(base_dest_item), mask="IN_DELETE Delete dir")


                # Если дубль события то выходим
                if Path(item).exists():
                    if item in filter and filter[item]['st_mtime'] == Path(item).stat().st_mtime and filter[item]['mask'] == mask:
                        break
                    filter[item] = {'time': time.time(), 'st_mtime': Path(
                        item).stat().st_mtime, 'mask': mask}
                else:
                    break


                if mask == "IN_MOVED_TO":
                    src_pathname = getattr(event, 'src_pathname', False)

                    if src_pathname != False: # Переименование, на следующей итерации, хотя лучше здесь
                        moved[src_pathname] = item
                        break
                    else: # Перемещение
                        if Path(item).is_dir():  # Если каталог то запускаем сканер
                            convert_tree(p)
                            break
                        else:  # Если файл то стартуем конвертер
                            mask = "IN_CLOSE_WRITE"


                if mask == "IN_CLOSE_WRITE" and Path(item).is_file():
                    # отсеиваем глюки, дубликаты, проверка предыдущего цикла
                    if Path(dest_item).is_file() and Path(dest_item).stat().st_mtime > Path(item).stat().st_mtime:
                        break
                    if not Path(item).is_file():
                        break

                    log(p, "Converting: " + dest_item,
                        mask="IN_CLOSE_WRITE Converting")

                  
                    if not Path(base_dest_item).is_dir():  # создаем подкаталог если нету
                        Path(base_dest_item).mkdir(parents=True, exist_ok=True)
                        os.chown(base_dest_item, uid, gid)

                    if extension == '.jpg' or extension == '.jpeg':
                        webp.cwebp(item, dest_item, "-quiet -pass 10 -m 6 -mt -q 80")
                        os.chown(dest_item, uid, gid)

                    if extension == '.png':
                        webp.cwebp(
                            item, dest_item,
                            "-quiet -pass 10 -m 6 -alpha_q 100 -mt -alpha_filter best -alpha_method 1 -q 80")
                        os.chown(dest_item, uid, gid)
                    
                    break
                break

        # Сообщаем, что элемент очереди queue_in обработан с помощью метода task_done
        queue_in.task_done()


def rm_tree(pth):  # удаление подкаталогов
    shutil.rmtree(pth)


def rm_empty_dir(pth): # Удаляем подкаталог если пустой
    for child in pth.glob("*"):
        if child.is_file() or child.is_dir():
            return False

    if not str(pth).endswith(result_path):
        pth.rmdir()
        return True


def convert_tree(pth): # Создание очереди при запуске, или событии с каталогами
    global queue_in, extension

    extensions = extension.split(',')
    event = Ev()
    dest = pth + result_path

    for child in Path(pth).glob('**/*'):
        # если это /webp то удалим отсутствующие копии
        if(str(child) + "/").startswith(dest + "/") and child.is_file():
            dest_item = str(child).replace(dest, pth)
            if not Path(dest_item).exists():
                if child.is_file():
                    log(pth, "Start convert_tree on Init: " + str(child),
                        mask="CONVERT_THREE Delete")
                    child.unlink()

                elif child.is_dir():
                    log(pth, "Start convert_tree on Init: " + str(child),
                        mask="CONVERT_THREE Delete dir")
                    rm_tree(str(child))
            continue

        if child.is_file() and all(not str(child).lower().endswith(ext) for ext in extensions):
            continue

        if child.is_file():  # Добавить в очередь если отсутствует или новее
            dest_item = str(child).replace(pth, dest)

            if not Path(dest_item).is_file():
                log(pth, "Start convert_tree on Init: " +
                    str(child))

                event.mask = "IN_CLOSE_WRITE"
                event.pathname = str(child)
                queue_in.put(event)
                time.sleep(0.1)
            elif Path(dest_item).stat().st_mtime < Path(child).stat().st_mtime:
                log(pth, "Start convert_tree on Init: " +
                    str(child))

                event.mask = "IN_CLOSE_WRITE"
                event.pathname = str(child)
                queue_in.put(event)
                time.sleep(0.1)


def log(path, str, mask=""):  # Логгер
    global result_path, log_level

    uid = os.stat(path).st_uid
    gid = os.stat(path).st_gid

    if not Path(path + result_path).is_dir():
        Path(path + result_path).mkdir(parents=True, exist_ok=True)
        os.chown(path + result_path, uid, gid)

    if log_level > 0:
        if log_level > 1:
            sys.stdout.write('%s\n' % (mask + " " + path + " " + str))
        with open(path + log_file, "a") as file:
            file.write(str + "\n")


def createParser (): # Разбор аргументов коммандной строки
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--stop', type=str, default=False)
    parser.add_argument('-b', '--background', type=str, default=False)
 
    return parser


def sigterm_handler(signum, frame):  # Завершение процессов
    global queue_in, notifier, pidFile, cons_p

    notifier.stop()

    event = Ev()
    event.mask = "SIG_TERM"
    sys.stdout.write("Waiting tasks to complete...\n")

    if queue_in.qsize() > 0: # Очистка очереди
        sys.stdout.write("Aborting %s tasks\n" % queue_in.qsize())

        while queue_in.qsize() > 0:
            sys.stdout.write("%s " % queue_in.qsize() )
            queue_in.get(False)
            queue_in.task_done()

    queue_in.put(event)
    time.sleep(2)
    queue_in.close()

    cons_p.terminate()
    sys.stdout.write("Shutting down...\n")
    
    if Path(pidFile).is_file():
        Path(pidFile).unlink()
    
    sys.exit(0)


if __name__ == '__main__': # Required arguments
    extension = ".jpg,.jpeg,.png"

    path = [
        "/var/www/www-root/data/www/site.ru",
        "/var/www/www-root/data/www/site2.ru"
    ]

    result_path = "/webp"  # Подкаталог для webp копий
    log_level = 3  # 2 - подробный, с выводом на экран. 1 - только инфо, в каталоге ~webp/images.log. 0 - Отключен
    log_file = result_path + "/images.log" # Лог файл создается в каталоге для копий
    
    pidFile = '/tmp/pyinotify.pid'

    parser = createParser()
    namespace = parser.parse_args(sys.argv[1:])

    libc = cdll.LoadLibrary("libc.so.6")

    if Path(pidFile).is_file():  # Проверка запуска копии, вывод справки
        with open(pidFile, "r") as file:
            nums = file.read().splitlines()
        if 'stop' in namespace:
            if namespace.stop:  # Выход из запущенного процесса
                pid = int(nums[0])
                sys.stdout.write("Terminate another copy pid: %d\n" % pid)

                if Path("/proc/" + nums[0]).exists():
                    os.kill(pid, signal.SIGTERM)
                
                if Path(pidFile).is_file():
                    Path(pidFile).unlink()
                    sys.exit(0)

        sys.stdout.write("Runned another copy pid: %d\n" % int(nums[0]))
        sys.exit(0)
    else:
        if 'stop' in namespace:
            if namespace.stop:  # Выход из запущенного процесса
                sys.stdout.write('Not started another copy\n')
                sys.exit(0)


    pid = libc.getpid()
    with open(pidFile, "w") as file:
        file.write(str(pid))
    sys.stdout.write("Start monitoring pid %d (type c^c to exit)\n" % pid)


    if 'background' in namespace: # Запуск в фоновом режиме
        if namespace.background:
            ppid = os.fork()

            if ppid > 0:
                sys.exit(0)
            else:
                ppid = libc.getpid()
                sys.stdout.write("Start in background %d\n" % (ppid))
                with open(pidFile, "w") as file:
                    file.write(str(ppid))
                sys.stdout = open('/dev/null', 'w')


    queue_in = multiprocessing.JoinableQueue()  # объект очереди

    # создаем подпроцесс для клиентской функции
    cons_p = multiprocessing.Process(target=converter, args=(queue_in, path))
    cons_p.daemon = True  # ставим флаг, что данный процесс является демоническим
    cons_p.start()  # стартуем процесс

    # Blocks monitoring
    mask = pyinotify.IN_DELETE | pyinotify.IN_MOVED_TO | pyinotify.IN_MOVED_FROM | pyinotify.IN_CLOSE_WRITE
    wm = pyinotify.WatchManager()
    handler = OnWriteHandler(path=path, extension=extension, queue_in=queue_in)
    notifier = pyinotify.Notifier(wm, default_proc_fun=handler)

    # Обработка сигналов завершения
    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    time.sleep(0.4)
    for pth in path:
        if Path(pth).is_dir():
            sys.stdout.write("==> Start monitoring %s\n" % pth)

            if log_level > 0: # Создание каталога для копий, и лог файла
                uid = os.stat(pth).st_uid
                gid = os.stat(pth).st_gid

                if not Path(pth + result_path).is_dir():
                    Path(pth + result_path).mkdir(parents=True, exist_ok=True)
                    os.chown(pth + result_path, uid, gid)
                if not Path(pth + log_file).is_file():
                    with open(pth + log_file, "w") as file:
                        pass
                    os.chown(pth + log_file, uid, gid)

            convert_tree(pth) # Сканирование каталогов при старте


    wm.add_watch(path, mask, rec=True, auto_add=True)
    notifier.loop()

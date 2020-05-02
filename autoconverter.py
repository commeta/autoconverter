#!/usr/bin/env python3
#
# Usage:
#   ./autoconverter.py
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
# yum install python-inotify.noarch python-inotify-examples.noarch 

from ctypes import cdll
import pyinotify
import multiprocessing
import time
from webptools import webplib as webp
from pathlib import Path


class Ev(object):
    # Event struct
    mask = ""
    pathname = ""
    dir = False
    mask = ""
    maskname = ""
    name = ""
    path = ""
    pathname = ""
    src_pathname = ""


class OnWriteHandler(pyinotify.ProcessEvent):
    # Создание очередей, слушатель inotify ядра
    def my_init(self, path, extension, queue_in):
        self.path = path
        self.extensions = extension.split(',')
        self.queue_in = queue_in

    def process_IN_CLOSE_WRITE(self, event):
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions):
            return
        if event.dir == True:
            return
        event.mask = "IN_CLOSE_WRITE"
        queue_in.put(event)  # добавляем элемент в очередь модификации

    def process_IN_DELETE(self, event):
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions):
            return
        if event.dir == True:
            return
        event.mask = "IN_DELETE"
        queue_in.put(event)  # добавляем элемент в очередь удаления

    def process_IN_MOVED_TO(self, event):
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions) and event.dir == False:
            return
        event.mask = "IN_MOVED_TO"
        # добавляем элемент в очередь, модификация или переименование
        queue_in.put(event)

    def process_IN_MOVED_FROM(self, event):
        if all(not event.pathname.lower().endswith(ext) for ext in self.extensions) and event.dir == False:
            return
        event.mask = "IN_MOVED_FROM"
        event.wait = True
        # добавляем элемент в очередь, удаление или переименование
        queue_in.put(event)


def converter(queue_in, path): # Обработчик очереди в отдельном процессе
    # Смена приоритета
    libc = cdll.LoadLibrary("libc.so.6")
    pid = libc.getpid()
    libc.setpriority(0, pid, 20)

    filter = {}
    moved = {}

    while True:
        event = queue_in.get()  # Извлекаем элемент из очереди
        mask = event.mask
        is_dir = event.dir
        item = event.pathname
        
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


                if not Path(dest).is_dir():  # создает каталог если нету /webp
                    Path(dest).mkdir(parents=True, exist_ok=True)


                if item.startswith(dest):  # если это /webp то выход
                    break
                

                if mask == "IN_MOVED_FROM": # Перемещение файла или каталога
                    if event.wait == False:
                        if item in moved:  # Внутреннее - переименовываем
                            # Проверить перемещение из разных точек наблюдения
                            moved_dest_item = moved[item].replace(p, dest)
                            log(p, "Rename: " + dest_item)
                            Path(dest_item).rename(moved_dest_item)
                            del moved[item]
                            break
                            
                        else: # Внешнее - удаляем
                            log(p, "Delete: " + dest_item)
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
                    log(p, "Delete: " + dest_item)
                    Path(dest_item).unlink()  # Удаляем файл

                    # Удаляем подкаталог если пустой
                    if rm_empty_dir(str(base_dest_item)):
                        log(p, "Delete dir: " + str(base_dest_item))


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

                    log(p, "Converting: " + dest_item)

                    if not Path(base_dest_item).is_dir():  # создаем подкаталог если нету
                        Path(base_dest_item).mkdir(
                            parents=True, exist_ok=True)

                    if extension == '.jpg' or extension == '.jpeg':
                        webp.cwebp(item, dest_item, "-quiet -pass 10 -m 6 -mt -q 80")
                        
                    if extension == '.png':
                        webp.cwebp(
                            item, dest_item, "-quiet -pass 10 -m 6 -alpha_q 100 -mt -alpha_filter best -alpha_method 1 -q 80")
                    
                    break


                break

        # Сообщаем, что элемент очереди queue_in обработан с помощью метода task_done
        queue_in.task_done()


def monitor(path, extension, queue_in): # watched events
    mask = pyinotify.IN_DELETE | pyinotify.IN_MOVED_TO | pyinotify.IN_MOVED_FROM | pyinotify.IN_CLOSE_WRITE
    wm = pyinotify.WatchManager()
    handler = OnWriteHandler(path=path, extension=extension, queue_in=queue_in)
    notifier = pyinotify.Notifier(wm, default_proc_fun=handler)
    wm.add_watch(path, mask, rec=True, auto_add=True)
    print ('==> Start monitoring %s (type c^c to exit)' % path)
    notifier.loop()


def rm_tree(pth): # удаление подкаталогов
    for child in Path(pth).glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


def rm_empty_dir(pth):
    is_empty = True  # Удаляем подкаталог если пустой
    for child in Path(pth).glob("*"):
        if child.is_file() or child.is_dir():
            is_empty = False
            return False

    if is_empty == True:
        if not str(pth).endswith(result_path):
            Path(pth).rmdir()
            return True
    
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
            if not Path(dest_item).is_file():
                log(pth, "Delete: " + str(child))

                Path(child).unlink()
                rm_empty_dir(Path(child).parent)
            continue

        if child.is_file() and all(not str(child).lower().endswith(ext) for ext in extensions):
            continue

        if child.is_file():  # Добавить в очередь если отсутствует или новее
            dest_item = str(child).replace(pth, dest)

            if not Path(dest_item).is_file():
                event.mask = "IN_CLOSE_WRITE"
                event.pathname = str(child)
                queue_in.put(event)
            elif Path(dest_item).stat().st_mtime < Path(child).stat().st_mtime:
                event.mask = "IN_CLOSE_WRITE"
                event.pathname = str(child)
                queue_in.put(event)
            time.sleep(0.1)


def log(path, str): # Логгер
    global result_path
    with open(path + result_path + "/images.log", "a") as file:
        file.write(str + "\n")


if __name__ == '__main__':
    # Required arguments
    extension = ".jpg,.jpeg,.png"

    path = [
        "/var/www/www-root/data/www/site.ru",
        "/var/www/www-root/data/www/site2.ru"
    ]

    result_path = "/webp" # Подкаталог для webp копий

    queue_in = multiprocessing.JoinableQueue()  # объект очереди
    # создаем подпроцесс для клиентской функции
    cons_p = multiprocessing.Process(target=converter, args=(queue_in, path))
    cons_p.daemon = True  # ставим флаг, что данный процесс является демоническим
    cons_p.start()  # стартуем процесс

    time.sleep(0.4)
    for pth in path:
        convert_tree(pth)


    # Blocks monitoring
    monitor(path, extension, queue_in)

    #queue_in.terminate()
    #queue_in.join()  # ждем пока чтобы клиент успел обработать все элементы

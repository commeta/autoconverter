# Autoconverter
Background converting png or jpeg files to webp format on Linux.

Бета версия фонового конвертера графических файлов.
Данная программа работает в фоновом режиме, ведет наблюдение за указанными каталогами.
В случае появления в них файлов с расширениями jpeg|jpg|png, создает копии графических файлов в подкаталоге ~webp/

Поддерживает: копирование, переименование, перемещение, удаление файлов.

Требования:
Linux, Python >= 3.5, Pyinotify, Webptools

Установка:
pip3 install pyinotify webptools

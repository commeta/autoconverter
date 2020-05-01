# Autoconverter
Background converting png or jpeg files to webp format on Linux.

### Бета версия фонового конвертера графических файлов.
Данная программа работает в фоновом режиме, ведет наблюдение за указанными каталогами.
В случае появления в них файлов с расширениями jpeg|jpg|png, создает копии графических файлов в подкаталоге ~webp/
Массив с путями каталогов для наблюдения можно прописать в файле скрипта:
```PYTHON
    path = [
        "/home/t/fanotify/tmp",
        "/home/t/fanotify/tmp2"
    ]
```

#### Поддерживает: 
копирование, переименование, перемещение, удаление файлов.

#### Требования:
Linux, Python >= 3.5, Pyinotify, Webptools

#### Установка зависимостей:
```BASH
pip3 install pyinotify webptools
```

#### Пример конфигурации NGINX для подмены на webp

```NGINX
server {
	server_name site.ru www.site.ru;
	ssl_certificate "/var/www/httpd-cert/www-root/site.ru_le1.crtca";
	ssl_certificate_key "/var/www/httpd-cert/www-root/site.ru_le1.key";
	ssl_ciphers EECDH:+AES256:-3DES:RSA+AES:!NULL:!RC4;
	ssl_prefer_server_ciphers on;
	ssl_protocols TLSv1 TLSv1.1 TLSv1.2;
	add_header Strict-Transport-Security "max-age=31536000;";
	ssl_dhparam /etc/ssl/certs/dhparam4096.pem;
	charset UTF-8;
	index index.php index.html;
	disable_symlinks if_not_owner from=$root_path;
	include /etc/nginx/vhosts-includes/*.conf;
	include /etc/nginx/vhosts-resources/site.ru/*.conf;
	access_log /var/www/httpd-logs/site.ru.access.log;
	error_log /var/www/httpd-logs/site.ru.error.log notice;
	set $root_path /var/www/www-root/data/www/site.ru;
	root $root_path;
	location / {
		location ~ [^/]\.ph(p\d*|tml)$ {
			try_files /does_not_exists @fallback;
		}
		location ~* ^.+\.(ico|gif|svg|js|css|mp3|ogg|mpe?g|avi|zip|gz|bz2?|rar|swf|woff|woff2|ttf)$ {
			try_files $uri $uri/ @fallback;
			expires 365d;
		}
		location ~* ^.+\.(jpg|jpeg|png)$ {
			set $ax 0;
			if ( $http_accept ~* "webp" ) {
			    set $ax 1;
			}
			if ( -e $root_path/webp$uri ){
			    set $ax "${ax}1";
			}
			if ( $ax = "11" ) {
			    rewrite ^ /webp$uri last;
			    return  403;
			}
			expires 365d;
			try_files $uri $uri/ @fallback;
		}
		location ^~ /webp/ {
		    types { } default_type "image/webp";
		    add_header Vary Accept;
		    expires 365d;
		    try_files $uri $uri/ @fallback;
		}
		location / {
			try_files /does_not_exists @fallback;
		}
	}
	location @fallback {
		proxy_pass http://127.0.0.1:8080;
		proxy_redirect http://127.0.0.1:8080 /;
		proxy_set_header Host $host;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_set_header X-Forwarded-Port $server_port;
		access_log off;
	}
	gzip on;
	gzip_comp_level 9;
	gzip_disable "msie6";
	gzip_vary on;
	gzip_types text/plain text/css application/json application/x-javascript text/xml application/xml application/xml+rss text/javascript application/javascript;
	listen xx.xx.xx.xx:xx ssl http2;
}
```

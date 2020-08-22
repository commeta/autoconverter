#/bin/bash

# Convert all images files in subdirectories, to ~webp/ directory
# apt install webp
# Usage ./image2webp.sh
# cron nice -n 15 /bin/bash -lc /var/www/user/data/www/site.domain/core/image2webp.sh

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin


startconverter() {
	local fullname="$1"
	
	if [[ "$fullname" =~ "$sitedir/webp/" ]]; then
		local webpfn=`echo ${fullname/"$sitedir/webp"/$sitedir}`

		if [[ ! -f "$webpfn" ]]; then
			rm -f $fullname
		fi
	else
		local webp=`echo ${fullname/$sitedir/"$sitedir/webp"}`
		local filename=`basename "$1"`
		local fileext="${filename##*.}"
		local ext2lower=`echo "$fileext" | tr A-Z a-z`			

		if [[ -e "$webp" ]]; then
			if [[ $(date -r "$webp" +%s) < $(date -r "$fullname" +%s) ]]; then
				if [[ $ext2lower == "jpg" || $ext2lower == "jpeg" ]]; then
					cwebp -metadata none -quiet -pass 10 -m 6 -mt -q 70 "$fullname" -o "$webp"
				else
					cwebp -metadata none -quiet -pass 10 -m 6 -alpha_q 85 -mt -alpha_filter best -alpha_method 1 -q 70 "$fullname" -o "$webp"
				fi
			fi
		else
			wdir=$(dirname "${webp}")
				
			if [[ ! -d "$wdir" ]]; then
				mkdir -p "$wdir"
			fi

			if [[ $ext2lower == "jpg" || $ext2lower == "jpeg" ]]; then
				cwebp -metadata none -quiet -pass 10 -m 6 -mt -q 70 "$fullname" -o "$webp"
			else
				cwebp -metadata none -quiet -pass 10 -m 6 -alpha_q 85 -mt -alpha_filter best -alpha_method 1 -q 70 "$fullname" -o "$webp"
			fi
		fi
	fi
}


scanimg() {
    find $sitedir \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) -type f | while read file; do
        startconverter "$file"
    done
}


[[ $(lsof -t $0| wc -l) > 1 ]] && exit

sitedir='/var/www/user/data/www/site.domain'

scanimg "$sitedir"
find "$sitedir/webp" -depth -type d -empty -delete

chown -R user:user /var/www/user/data/www/site.domain/webp/*

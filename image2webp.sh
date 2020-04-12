#/bin/bash

# Convert all images files in subdirectories, to ~webp/ directory
# apt install webp
# Usage ./image2webp.sh /home/t/tutboxing/fanotify/tmp

start() {
	local fullname="$1"
		if [[ "$fullname" =~ "webp/" ]]; then
			local webpfn=`echo ${fullname/"$dir/webp"/$dir}`
			
			if [[ ! -f "$webpfn" ]]; then
				rm -f $fullname
			fi
		else
			local webp=`echo ${fullname/$dir/"$dir/webp"}`
			local filename=`basename "$1"`
			local fileext="${filename##*.}"
			local ext2lower=`echo "$fileext" | tr A-Z a-z`			

			if [[ -e "$webp" ]]; then
				if [[ $(date -r "$webp" +%s) < $(date -r "$fullname" +%s) ]]; then
					if [[ $ext2lower == "jpg" || $ext2lower == "jpeg" ]]; then
						cwebp -quiet -pass 10 -m 6 -mt -q 80 "$fullname" -o "$webp"
					else
						cwebp -quiet -pass 10 -m 6 -alpha_q 100 -mt -alpha_filter best -alpha_method 1 -q 80 "$fullname" -o "$webp"
					fi
				fi
			else
				wdir=$(dirname "${webp}")
				
				if [[ ! -d "$wdir" ]]; then
					mkdir -p "$wdir"
				fi
				
				if [[ $ext2lower == "jpg" || $ext2lower == "jpeg" ]]; then
					cwebp -quiet -pass 10 -m 6 -mt -q 80 "$fullname" -o "$webp"
				else
					cwebp -quiet -pass 10 -m 6 -alpha_q 100 -mt -alpha_filter best -alpha_method 1 -q 80 "$fullname" -o "$webp"
				fi
			fi
		fi
}

scan() {
	local x;
	for e in "$1"/*; do
		x=${e##*/}
		if [ -d "$e" -a ! -L "$e" ]
		then
			scan "$e"
		else
			start "$e"
		fi
	done
}


scanimg() {
    find $path \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) | while read file; do
        start "$file"
    done

}


[[ $(lsof -t $0| wc -l) > 1 ]] && exit
 
[ $# -eq 0 ] && path=`pwd` || path=$@

dir=`basename $path`
scanimg "$path"



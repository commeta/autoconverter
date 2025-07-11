#!/bin/bash

# Script for converting images to WebP
# Requirements: webp, imagemagick (optional), parallel (optional)
# Installation: apt install webp imagemagick parallel
# Usage: ./image2webp.sh [OPTIONS]
# Cron: nice -n 15 /bin/bash -lc "/path/to/image2webp.sh --quiet"

set -euo pipefail

# Default configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_NAME="$(basename "$0")"
readonly LOCK_FILE="/tmp/${SCRIPT_NAME}.lock"
readonly LOG_FILE="/tmp/${SCRIPT_NAME}.log"

# Default settings
DEFAULT_SITE_DIR="/var/www/www-root/data/www/site.ru"
DEFAULT_WEBP_DIR="webp"
DEFAULT_QUALITY=75
DEFAULT_ALPHA_QUALITY=85
DEFAULT_THREADS=$(nproc)
DEFAULT_OWNER="user:user"

# Configuration variables
SITE_DIR="${SITE_DIR:-$DEFAULT_SITE_DIR}"
WEBP_DIR="${WEBP_DIR:-$DEFAULT_WEBP_DIR}"
QUALITY="${QUALITY:-$DEFAULT_QUALITY}"
ALPHA_QUALITY="${ALPHA_QUALITY:-$DEFAULT_ALPHA_QUALITY}"
THREADS="${THREADS:-$DEFAULT_THREADS}"
OWNER="${OWNER:-$DEFAULT_OWNER}"
VERBOSE=false
QUIET=false
DRY_RUN=false
FORCE=false
PARALLEL_JOBS=4

# Supported formats
readonly SUPPORTED_FORMATS=("jpg" "jpeg" "png" "gif" "bmp" "tiff" "tif" "webp")

# Global variables for parallel processing
export TEMP_FILE_LIST=""

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        ERROR)
            echo "[$timestamp] ERROR: $message" >&2
            [[ ! "$QUIET" == true ]] && echo "[$timestamp] ERROR: $message" >> "$LOG_FILE"
            ;;
        WARN)
            echo "[$timestamp] WARN: $message" >&2
            [[ ! "$QUIET" == true ]] && echo "[$timestamp] WARN: $message" >> "$LOG_FILE"
            ;;
        INFO)
            [[ "$VERBOSE" == true ]] && echo "[$timestamp] INFO: $message"
            [[ ! "$QUIET" == true ]] && echo "[$timestamp] INFO: $message" >> "$LOG_FILE"
            ;;
        DEBUG)
            [[ "$VERBOSE" == true ]] && echo "[$timestamp] DEBUG: $message"
            ;;
    esac
}

# Function to show help
show_help() {
    cat << EOF
Usage: $SCRIPT_NAME [OPTIONS]

Converts images to WebP format with size and quality optimization.

OPTIONS:
    -s, --site-dir DIR      Site directory (default: $DEFAULT_SITE_DIR)
    -w, --webp-dir DIR      Subdirectory for WebP files (default: $DEFAULT_WEBP_DIR)
    -q, --quality NUM       Compression quality 0-100 (default: $DEFAULT_QUALITY)
    -a, --alpha-quality NUM Alpha channel quality 0-100 (default: $DEFAULT_ALPHA_QUALITY)
    -t, --threads NUM       Number of threads (default: $DEFAULT_THREADS)
    -o, --owner USER:GROUP  File owner (default: $DEFAULT_OWNER)
    -j, --jobs NUM          Parallel jobs (default: $PARALLEL_JOBS)
    -v, --verbose           Verbose output
    --quiet                 Quiet mode
    --dry-run               Show what would be done without executing
    --force                 Force recreation of all WebP files
    -h, --help              Show this help

Examples:
    $SCRIPT_NAME --verbose
    $SCRIPT_NAME --site-dir /var/www/html --quality 80
    $SCRIPT_NAME --dry-run --force
    
Environment variables:
    SITE_DIR, WEBP_DIR, QUALITY, ALPHA_QUALITY, THREADS, OWNER
EOF
}

# Function to check dependencies
check_dependencies() {
    local missing_deps=()
    
    if ! command -v cwebp &> /dev/null; then
        missing_deps+=("webp")
    fi
    
    if ! command -v identify &> /dev/null; then
        log WARN "imagemagick not found. Some features may be unavailable."
    fi
    
    if ! command -v parallel &> /dev/null; then
        log WARN "parallel not found. Sequential processing will be used."
    fi
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log ERROR "Missing required dependencies: ${missing_deps[*]}"
        log ERROR "Install: apt install ${missing_deps[*]}"
        exit 1
    fi
}

# Function to create lock
create_lock() {
    if [[ -f "$LOCK_FILE" ]]; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log ERROR "Script is already running (PID: $pid)"
            exit 1
        else
            log WARN "Found stale lock file, removing..."
            rm -f "$LOCK_FILE"
        fi
    fi
    
    echo $$ > "$LOCK_FILE"
    trap 'cleanup_and_exit' INT TERM EXIT
}

# Cleanup function
cleanup_and_exit() {
    [[ -f "$LOCK_FILE" ]] && rm -f "$LOCK_FILE"
    [[ -n "$TEMP_FILE_LIST" ]] && [[ -f "$TEMP_FILE_LIST" ]] && rm -f "$TEMP_FILE_LIST"
    exit
}

# Function to check supported format
is_supported_format() {
    local ext="$1"
    local lower_ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    
    for format in "${SUPPORTED_FORMATS[@]}"; do
        if [[ "$lower_ext" == "$format" ]]; then
            return 0
        fi
    done
    return 1
}

# Function to get file size
get_file_size() {
    local file="$1"
    if [[ -f "$file" ]]; then
        stat -c%s "$file" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Function to convert a single file
convert_single_file() {
    local source_file="$1"
    local webp_full_path="${SITE_DIR}/${WEBP_DIR}"
    local relative_path="${source_file#$SITE_DIR/}"
    local webp_file="${webp_full_path}/${relative_path%.*}.webp"
    local webp_dir=$(dirname "$webp_file")
    
    # Check if the file is already in the webp directory
    if [[ "$source_file" == *"/$WEBP_DIR/"* ]]; then
        log DEBUG "Skipping file in webp directory: $source_file"
        return 0
    fi
    
    # Check file extension
    local filename=$(basename "$source_file")
    local extension="${filename##*.}"
    
    if ! is_supported_format "$extension"; then
        log DEBUG "Unsupported format: $source_file"
        return 0
    fi
    
    # Check if conversion is needed
    if [[ -f "$webp_file" && "$FORCE" != true ]]; then
        if [[ $(stat -c%Y "$webp_file" 2>/dev/null || echo 0) -ge $(stat -c%Y "$source_file" 2>/dev/null || echo 0) ]]; then
            log DEBUG "WebP file is up to date: $webp_file"
            return 0
        fi
    fi
    
    log INFO "Converting: $source_file -> $webp_file"
    
    if [[ "$DRY_RUN" == true ]]; then
        echo "DRY RUN: $source_file -> $webp_file"
        return 0
    fi
    
    # Create directory if needed
    if [[ ! -d "$webp_dir" ]]; then
        mkdir -p "$webp_dir"
    fi
    
    # Define conversion parameters
    local cwebp_args=()
    cwebp_args+=("-metadata" "none")
    cwebp_args+=("-quiet")
    cwebp_args+=("-pass" "10")
    cwebp_args+=("-m" "6")
    cwebp_args+=("-mt")
    cwebp_args+=("-q" "$QUALITY")
    
    # For files with alpha channel
    local lower_ext=$(echo "$extension" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower_ext" == "png" || "$lower_ext" == "gif" ]]; then
        cwebp_args+=("-alpha_q" "$ALPHA_QUALITY")
        cwebp_args+=("-alpha_filter" "best")
        cwebp_args+=("-alpha_method" "1")
    fi
    
    # Perform conversion
    if cwebp "${cwebp_args[@]}" "$source_file" -o "$webp_file" 2>/dev/null; then
        local original_size=$(get_file_size "$source_file")
        local webp_size=$(get_file_size "$webp_file")
        local savings=0
        
        if [[ "$original_size" -gt 0 ]]; then
            savings=$(( (original_size - webp_size) * 100 / original_size ))
        fi
        
        log INFO "Successful: $webp_file (savings: ${savings}%)"
        return 0
    else
        log ERROR "Conversion error: $source_file"
        return 1
    fi
}

# Function to clean up orphaned WebP files
cleanup_orphaned_webp() {
    local webp_full_path="${SITE_DIR}/${WEBP_DIR}"
    
    if [[ ! -d "$webp_full_path" ]]; then
        return 0
    fi
    
    log INFO "Cleaning up orphaned WebP files..."
    
    find "$webp_full_path" -name "*.webp" -type f | while read -r webp_file; do
        local relative_path="${webp_file#$webp_full_path/}"
        local base_name="${relative_path%.*}"
        local found=false
        
        # Look for the corresponding original file
        for ext in "${SUPPORTED_FORMATS[@]}"; do
            if [[ "$ext" == "webp" ]]; then
                continue
            fi
            
            local original_file="${SITE_DIR}/${base_name}.${ext}"
            if [[ -f "$original_file" ]]; then
                found=true
                break
            fi
        done
        
        if [[ "$found" == false ]]; then
            log INFO "Removing orphaned WebP file: $webp_file"
            if [[ "$DRY_RUN" != true ]]; then
                rm -f "$webp_file"
            fi
        fi
    done
    
    # Remove empty directories
    if [[ "$DRY_RUN" != true ]]; then
        find "$webp_full_path" -type d -empty -delete 2>/dev/null || true
    fi
}

# Function to create supported formats string for find
create_find_expression() {
    local expr="("
    for i in "${!SUPPORTED_FORMATS[@]}"; do
        if [[ $i -gt 0 ]]; then
            expr+=" -o"
        fi
        expr+=" -iname *.${SUPPORTED_FORMATS[$i]}"
    done
    expr+=" )"
    echo "$expr"
}

# Main function for searching and converting
process_images() {
    local file_count=0
    local converted_count=0
    local error_count=0
    
    log INFO "Starting image processing in: $SITE_DIR"
    
    # Create a temporary file for file list
    TEMP_FILE_LIST=$(mktemp)
    if [[ ! -f "$TEMP_FILE_LIST" ]]; then
        log ERROR "Failed to create temporary file"
        exit 1
    fi
    
    # Find all supported image files
    local find_cmd="find \"$SITE_DIR\" -type f"
    
    # Add format conditions
    find_cmd+=" \\( "
    for i in "${!SUPPORTED_FORMATS[@]}"; do
        if [[ $i -gt 0 ]]; then
            find_cmd+=" -o"
        fi
        find_cmd+=" -iname \"*.${SUPPORTED_FORMATS[$i]}\""
    done
    find_cmd+=" \\)"
    
    # Exclude webp directory
    find_cmd+=" ! -path \"*/$WEBP_DIR/*\""
    
    # Execute find command
    eval "$find_cmd" > "$TEMP_FILE_LIST"
    
    file_count=$(wc -l < "$TEMP_FILE_LIST")
    log INFO "Found images to process: $file_count"
    
    if [[ $file_count -eq 0 ]]; then
        log INFO "No files to process"
        return 0
    fi
    
    # Process files
    if command -v parallel &> /dev/null && [[ "$PARALLEL_JOBS" -gt 1 ]]; then
        log INFO "Using parallel processing ($PARALLEL_JOBS jobs)"
        
        # Export necessary functions and variables
        export -f convert_single_file log get_file_size is_supported_format
        export SITE_DIR WEBP_DIR QUALITY ALPHA_QUALITY VERBOSE QUIET DRY_RUN FORCE
        export LOG_FILE
        
        # Export supported formats as a string
        export SUPPORTED_FORMATS_STR="${SUPPORTED_FORMATS[*]}"
        
        # Create a wrapper function that reconstructs the array
        parallel_wrapper() {
            local file="$1"
            # Reconstruct SUPPORTED_FORMATS array
            IFS=' ' read -ra SUPPORTED_FORMATS <<< "$SUPPORTED_FORMATS_STR"
            convert_single_file "$file"
        }
        export -f parallel_wrapper
        
        # Use parallel to process files
        parallel -j "$PARALLEL_JOBS" parallel_wrapper :::: "$TEMP_FILE_LIST"
    else
        log INFO "Using sequential processing"
        while IFS= read -r file; do
            if [[ -n "$file" ]]; then
                if convert_single_file "$file"; then
                    ((converted_count++))
                else
                    ((error_count++))
                fi
            fi
        done < "$TEMP_FILE_LIST"
        
        log INFO "Processed: $converted_count, errors: $error_count"
    fi
}

# Function to set file ownership
set_ownership() {
    local webp_full_path="${SITE_DIR}/${WEBP_DIR}"
    
    if [[ -d "$webp_full_path" && "$DRY_RUN" != true ]]; then
        log INFO "Setting owner: $OWNER"
        if chown -R "$OWNER" "$webp_full_path" 2>/dev/null; then
            log INFO "Owner set successfully"
        else
            log WARN "Failed to set owner (root privileges may be required)"
        fi
    fi
}

# Function to validate configuration
validate_config() {
    if [[ ! -d "$SITE_DIR" ]]; then
        log ERROR "Site directory does not exist: $SITE_DIR"
        exit 1
    fi
    
    if [[ ! -r "$SITE_DIR" ]]; then
        log ERROR "No read permissions for directory: $SITE_DIR"
        exit 1
    fi
    
    if [[ "$QUALITY" -lt 0 || "$QUALITY" -gt 100 ]]; then
        log ERROR "Quality must be between 0 and 100: $QUALITY"
        exit 1
    fi
    
    if [[ "$ALPHA_QUALITY" -lt 0 || "$ALPHA_QUALITY" -gt 100 ]]; then
        log ERROR "Alpha quality must be between 0 and 100: $ALPHA_QUALITY"
        exit 1
    fi
    
    if [[ "$THREADS" -lt 1 ]]; then
        log ERROR "Number of threads must be greater than 0: $THREADS"
        exit 1
    fi
    
    if [[ "$PARALLEL_JOBS" -lt 1 ]]; then
        log ERROR "Number of parallel jobs must be greater than 0: $PARALLEL_JOBS"
        exit 1
    fi
}

# Command-line argument parsing
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--site-dir)
                SITE_DIR="$2"
                shift 2
                ;;
            -w|--webp-dir)
                WEBP_DIR="$2"
                shift 2
                ;;
            -q|--quality)
                QUALITY="$2"
                shift 2
                ;;
            -a|--alpha-quality)
                ALPHA_QUALITY="$2"
                shift 2
                ;;
            -t|--threads)
                THREADS="$2"
                shift 2
                ;;
            -o|--owner)
                OWNER="$2"
                shift 2
                ;;
            -j|--jobs)
                PARALLEL_JOBS="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            --quiet)
                QUIET=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                log ERROR "Unknown argument: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Main function
main() {
    local start_time=$(date +%s)
    
    # Parse arguments
    parse_args "$@"
    
    # Validate configuration
    validate_config
    
    # Check dependencies
    check_dependencies
    
    # Create lock
    create_lock
    
    log INFO "Starting image conversion script"
    log INFO "Site directory: $SITE_DIR"
    log INFO "WebP directory: $WEBP_DIR"
    log INFO "Quality: $QUALITY, Alpha: $ALPHA_QUALITY"
    log INFO "Threads: $THREADS, Parallel jobs: $PARALLEL_JOBS"
    
    # Process images
    process_images
    
    # Clean up orphaned files
    cleanup_orphaned_webp
    
    # Set ownership
    set_ownership
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log INFO "Conversion completed in ${duration} seconds"
}

# Run the script
main "$@"

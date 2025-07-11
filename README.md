# WebP AutoConverter

A modern, efficient background service for converting PNG/JPEG images to WebP format on Linux systems.

## Features

- **Architecture**: Built with Python 3.8+ using async/await patterns
- **High Performance**: Multi-threaded conversion with configurable worker pools
- **Smart Event Handling**: Debounced file system events to prevent duplicate processing
- **Flexible Configuration**: YAML/JSON configuration files
- **Comprehensive Logging**: Configurable logging levels and file output
- **Metadata Preservation**: Optionally preserve EXIF data in converted images
- **Graceful Shutdown**: Proper signal handling and cleanup
- **Systemd Integration**: Ready-to-use service files

## Installation

### Prerequisites
- Python 3.8+
- Linux system with systemd (optional)

### Install Dependencies
```bash
pip3 install -r requirements.txt
```

### Basic Setup
1. Copy the script to desired location
2. Create configuration file:
   ```bash
   python3 autoconverter.py --create-config config.yaml
   ```
3. Edit configuration file to set your watch paths
4. Run the converter:
   ```bash
   python3 autoconverter.py -c config.yaml
   ```

### System Service Installation
Use the provided installation script:
```bash
chmod +x install.sh
./install.sh
```

## Configuration

All configuration is done via YAML or JSON files. Key settings:

- `watch_paths`: List of directories to monitor
- `output_subdir`: Subdirectory name for WebP files (default: "webp")
- `webp_quality`: WebP quality level (0-100)
- `max_workers`: Number of concurrent conversion threads
- `debounce_time`: Delay before processing duplicate events

## Usage

### Command Line Options
```bash
python3 autoconverter.py [options]

Options:
  -c, --config CONFIG     Configuration file path
  --create-config FILE    Create sample configuration file
  -d, --daemon           Run as daemon
  --pid-file FILE        PID file path
```

### Service Management
```bash
# Start service
sudo systemctl start autoconverter

# Stop service
sudo systemctl stop autoconverter

# Enable auto-start
sudo systemctl enable autoconverter

# Check status
sudo systemctl status autoconverter

# View logs
sudo journalctl -u autoconverter -f
```

## NGINX Configuration

The original NGINX configuration remains compatible:

```nginx
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
```

## Monitoring

The service provides comprehensive logging:

- **INFO**: Basic operation information
- **DEBUG**: Detailed processing information
- **WARNING**: Non-critical issues
- **ERROR**: Critical errors

Logs can be viewed via:
- System journal: `journalctl -u autoconverter`
- Log file: Check configured log file path
- Console output: When running in foreground

## Performance Optimization

- Adjust `max_workers` based on CPU cores
- Increase `debounce_time` for high-frequency file changes
- Use `webp_lossless: false` for better compression
- Monitor system resources and adjust accordingly

## Troubleshooting

### Common Issues

1. **Permission Errors**: Ensure the service user has read/write access to watch paths
2. **High CPU Usage**: Reduce `max_workers` or increase `debounce_time`
3. **Missing Conversions**: Check file extensions in `supported_extensions`
4. **Service Won't Start**: Verify configuration file syntax and paths

### Debug Mode
Run with debug logging to troubleshoot issues:
```bash
python3 autoconverter.py -c config.yaml --log-level DEBUG
```

## Migration from Old Version

The new version is not directly compatible with the old script. To migrate:

1. Stop the old service
2. Note your current watch paths
3. Install the new version
4. Update configuration with your paths
5. Start the new service
6. Verify operation

## License

This project is provided as-is for educational and production use.

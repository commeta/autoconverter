#!/usr/bin/env python3
"""
Usage:

python3 autoconverter.py [options]

Options:
  -c, --config CONFIG     Configuration file path
  --create-config FILE    Create sample configuration file
  -d, --daemon           Run as daemon
  --pid-file FILE        PID file path
  
Blocks monitoring |path| and its subdirectories for modifications on
files ending with suffix |*.jpg,*.png|. Run |cwebp| each time a modification
is detected. 
"""

import asyncio
import argparse
import logging
import os
import sys
import signal
import shutil
import time
import json
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import hashlib

# Modern dependencies
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from PIL import Image
import yaml


@dataclass
class Config:
    """Configuration dataclass"""
    watch_paths: List[str]
    output_subdir: str = "webp"
    supported_extensions: List[str] = None
    webp_quality: int = 80
    webp_method: int = 6
    webp_lossless: bool = False
    log_level: str = "INFO"
    log_file: Optional[str] = None
    max_workers: int = 4
    debounce_time: float = 1.0
    preserve_metadata: bool = True
    
    def __post_init__(self):
        if self.supported_extensions is None:
            self.supported_extensions = ['.jpg', '.jpeg', '.png']


class ImageConverter:
    """Modern image converter using Pillow"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    def convert_to_webp(self, source_path: Path, dest_path: Path) -> bool:
        """Convert image to WebP format"""
        try:
            # Ensure destination directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open and convert image
            with Image.open(source_path) as img:
                # Convert to RGB if necessary (for PNG with transparency)
                if img.mode in ('RGBA', 'LA', 'P'):
                    if source_path.suffix.lower() == '.png':
                        # Keep transparency for PNG
                        img = img.convert('RGBA')
                    else:
                        # Convert to RGB for JPEG
                        img = img.convert('RGB')
                
                # Prepare WebP save options
                save_options = {
                    'format': 'WebP',
                    'quality': self.config.webp_quality,
                    'method': self.config.webp_method,
                    'lossless': self.config.webp_lossless
                }
                
                # Preserve metadata if requested
                if self.config.preserve_metadata:
                    save_options['exif'] = img.info.get('exif', b'')
                
                # Save as WebP
                img.save(dest_path, **save_options)
                
            # Copy file timestamps and permissions
            self._copy_file_metadata(source_path, dest_path)
            
            self.logger.info(f"Converted: {source_path} -> {dest_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to convert {source_path}: {e}")
            return False
    
    def _copy_file_metadata(self, source: Path, dest: Path):
        """Copy file metadata from source to destination"""
        try:
            stat = source.stat()
            os.utime(dest, (stat.st_atime, stat.st_mtime))
            os.chmod(dest, stat.st_mode)
            os.chown(dest, stat.st_uid, stat.st_gid)
        except (OSError, PermissionError) as e:
            self.logger.warning(f"Could not copy metadata from {source} to {dest}: {e}")


class FileEventHandler(FileSystemEventHandler):
    """Modern file system event handler"""
    
    def __init__(self, config: Config, event_queue: asyncio.Queue):
        super().__init__()
        self.config = config
        self.event_queue = event_queue
        self.logger = logging.getLogger(__name__)
        self.supported_extensions = set(ext.lower() for ext in config.supported_extensions)
        
    def _should_process_file(self, file_path: Path) -> bool:
        """Check if file should be processed"""
        if not file_path.exists() or file_path.is_dir():
            return False
            
        # Skip if file is in output directory
        if f"/{self.config.output_subdir}/" in str(file_path):
            return False
            
        # Check extension
        return file_path.suffix.lower() in self.supported_extensions
    
    def _queue_event(self, event_type: str, file_path: Path):
        """Queue an event for processing"""
        try:
            self.event_queue.put_nowait({
                'type': event_type,
                'path': file_path,
                'timestamp': time.time()
            })
        except asyncio.QueueFull:
            self.logger.warning(f"Event queue full, dropping event for {file_path}")
    
    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            file_path = Path(event.src_path)
            if self._should_process_file(file_path):
                self._queue_event('created', file_path)
    
    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            file_path = Path(event.src_path)
            if self._should_process_file(file_path):
                self._queue_event('modified', file_path)
    
    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            src_path = Path(event.src_path)
            dest_path = Path(event.dest_path)
            
            # Handle source file (deletion)
            if self._should_process_file(src_path):
                self._queue_event('deleted', src_path)
            
            # Handle destination file (creation)
            if self._should_process_file(dest_path):
                self._queue_event('moved', dest_path)
    
    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            file_path = Path(event.src_path)
            if self._should_process_file(file_path):
                self._queue_event('deleted', file_path)


class AutoConverter:
    """Main autoconverter class"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = self._setup_logging()
        self.event_queue = asyncio.Queue(maxsize=1000)
        self.converter = ImageConverter(config)
        self.observer = Observer()
        self.executor = ThreadPoolExecutor(max_workers=config.max_workers)
        self.pending_events: Dict[str, float] = {}
        self.running = False
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, self.config.log_level.upper()))
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # File handler (if specified)
        if self.config.log_file:
            file_handler = logging.FileHandler(self.config.log_file)
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        # Simple formatter for console
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def _get_webp_path(self, original_path: Path) -> Path:
        """Get corresponding WebP path for original file"""
        for watch_path in self.config.watch_paths:
            watch_path = Path(watch_path)
            if original_path.is_relative_to(watch_path):
                relative_path = original_path.relative_to(watch_path)
                webp_path = watch_path / self.config.output_subdir / relative_path
                return webp_path.with_suffix('.webp')
        
        # Fallback
        return original_path.with_suffix('.webp')
    
    async def _process_events(self):
        """Process file system events"""
        while self.running:
            try:
                # Get event with timeout
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                
                file_path = event['path']
                event_type = event['type']
                timestamp = event['timestamp']
                
                # Debounce events
                file_key = str(file_path)
                if file_key in self.pending_events:
                    # Skip if we have a recent event for this file
                    if timestamp - self.pending_events[file_key] < self.config.debounce_time:
                        continue
                
                self.pending_events[file_key] = timestamp
                
                # Process event
                if event_type in ['created', 'modified', 'moved']:
                    await self._handle_file_change(file_path)
                elif event_type == 'deleted':
                    await self._handle_file_deletion(file_path)
                
                # Clean up old pending events
                current_time = time.time()
                self.pending_events = {
                    k: v for k, v in self.pending_events.items()
                    if current_time - v < self.config.debounce_time * 2
                }
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.error(f"Error processing event: {e}")
    
    async def _handle_file_change(self, file_path: Path):
        """Handle file creation/modification"""
        if not file_path.exists():
            return
        
        webp_path = self._get_webp_path(file_path)
        
        # Check if conversion is needed
        if (webp_path.exists() and 
            webp_path.stat().st_mtime > file_path.stat().st_mtime):
            return
        
        # Convert in thread pool
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            self.executor, 
            self.converter.convert_to_webp, 
            file_path, 
            webp_path
        )
        
        if success:
            self.logger.info(f"Converted {file_path} to {webp_path}")
    
    async def _handle_file_deletion(self, file_path: Path):
        """Handle file deletion"""
        webp_path = self._get_webp_path(file_path)
        
        if webp_path.exists():
            try:
                webp_path.unlink()
                self.logger.info(f"Removed {webp_path}")
                
                # Clean up empty directories
                self._cleanup_empty_dirs(webp_path.parent)
                
            except Exception as e:
                self.logger.error(f"Failed to remove {webp_path}: {e}")
    
    def _cleanup_empty_dirs(self, directory: Path):
        """Remove empty directories"""
        try:
            if directory.exists() and directory.is_dir():
                if not any(directory.iterdir()):  # Directory is empty
                    # Don't remove the main output directory
                    if directory.name != self.config.output_subdir:
                        directory.rmdir()
                        self.logger.debug(f"Removed empty directory: {directory}")
                        # Recursively clean parent directories
                        self._cleanup_empty_dirs(directory.parent)
        except Exception as e:
            self.logger.debug(f"Could not remove directory {directory}: {e}")
    
    def _scan_existing_files(self):
        """Scan existing files and queue for conversion if needed"""
        self.logger.info("Scanning existing files...")
        
        for watch_path in self.config.watch_paths:
            watch_path = Path(watch_path)
            if not watch_path.exists():
                self.logger.warning(f"Watch path does not exist: {watch_path}")
                continue
                
            for file_path in watch_path.rglob('*'):
                if (file_path.is_file() and 
                    file_path.suffix.lower() in self.config.supported_extensions):
                    
                    # Skip files in output directory
                    if f"/{self.config.output_subdir}/" in str(file_path):
                        continue
                    
                    webp_path = self._get_webp_path(file_path)
                    
                    # Queue for conversion if needed
                    if (not webp_path.exists() or 
                        webp_path.stat().st_mtime < file_path.stat().st_mtime):
                        
                        try:
                            self.event_queue.put_nowait({
                                'type': 'created',
                                'path': file_path,
                                'timestamp': time.time()
                            })
                        except asyncio.QueueFull:
                            self.logger.warning(f"Queue full, skipping {file_path}")
    
    def _setup_file_watcher(self):
        """Setup file system watcher"""
        handler = FileEventHandler(self.config, self.event_queue)
        
        for watch_path in self.config.watch_paths:
            watch_path = Path(watch_path)
            if watch_path.exists():
                self.observer.schedule(handler, str(watch_path), recursive=True)
                self.logger.info(f"Watching: {watch_path}")
            else:
                self.logger.warning(f"Watch path does not exist: {watch_path}")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down...")
            self.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start(self):
        """Start the autoconverter"""
        self.logger.info("Starting AutoConverter...")
        self.running = True
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Setup file watcher
        self._setup_file_watcher()
        
        # Start observer
        self.observer.start()
        
        # Scan existing files
        self._scan_existing_files()
        
        # Start event processing
        await self._process_events()
    
    def stop(self):
        """Stop the autoconverter"""
        self.logger.info("Stopping AutoConverter...")
        self.running = False
        self.observer.stop()
        self.observer.join()
        self.executor.shutdown(wait=True)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or use defaults"""
    if config_path and Path(config_path).exists():
        with open(config_path, 'r') as f:
            if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                config_data = yaml.safe_load(f)
            else:
                config_data = json.load(f)
        return Config(**config_data)
    else:
        # Default configuration
        return Config(
            watch_paths=[
                "/var/www/www-root/data/www/site.ru",
                "/var/www/www-root/data/www/site2.ru"
            ]
        )


def create_sample_config(config_path: str):
    """Create a sample configuration file"""
    config = Config(
        watch_paths=[
            "/path/to/watch1",
            "/path/to/watch2"
        ],
        output_subdir="webp",
        supported_extensions=[".jpg", ".jpeg", ".png"],
        webp_quality=80,
        webp_method=6,
        webp_lossless=False,
        log_level="INFO",
        log_file="/var/log/autoconverter.log",
        max_workers=4,
        debounce_time=1.0,
        preserve_metadata=True
    )
    
    with open(config_path, 'w') as f:
        if config_path.endswith('.yaml') or config_path.endswith('.yml'):
            yaml.dump(asdict(config), f, default_flow_style=False)
        else:
            json.dump(asdict(config), f, indent=2)
    
    print(f"Sample configuration created at: {config_path}")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Modern WebP AutoConverter")
    parser.add_argument('-c', '--config', type=str, help='Configuration file path')
    parser.add_argument('--create-config', type=str, help='Create sample configuration file')
    parser.add_argument('-d', '--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--pid-file', type=str, default='/tmp/autoconverter.pid', 
                       help='PID file path')
    
    args = parser.parse_args()
    
    if args.create_config:
        create_sample_config(args.create_config)
        return
    
    # Load configuration
    config = load_config(args.config)
    
    # Create PID file
    if args.daemon:
        with open(args.pid_file, 'w') as f:
            f.write(str(os.getpid()))
    
    # Start autoconverter
    autoconverter = AutoConverter(config)
    
    try:
        await autoconverter.start()
    except KeyboardInterrupt:
        autoconverter.stop()
    finally:
        # Clean up PID file
        if args.daemon and Path(args.pid_file).exists():
            Path(args.pid_file).unlink()


if __name__ == '__main__':
    asyncio.run(main())

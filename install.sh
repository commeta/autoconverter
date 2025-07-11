#!/bin/bash
# Installation script for Modern AutoConverter

set -e

echo "Installing Modern AutoConverter..."

# Create directories
sudo mkdir -p /opt/autoconverter
sudo mkdir -p /etc/autoconverter

# Copy files
sudo cp autoconverter.py /opt/autoconverter/
sudo cp config.yaml /etc/autoconverter/
sudo cp autoconverter.service /etc/systemd/system/

# Set permissions
sudo chown -R www-data:www-data /opt/autoconverter
sudo chmod +x /opt/autoconverter/autoconverter.py

# Install Python dependencies
pip3 install -r requirements.txt

# Reload systemd
sudo systemctl daemon-reload

echo "Installation complete!"
echo "Edit /etc/autoconverter/config.yaml to configure watch paths"
echo "Start service with: sudo systemctl start autoconverter"
echo "Enable auto-start with: sudo systemctl enable autoconverter"

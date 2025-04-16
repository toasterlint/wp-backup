#!/usr/bin/env python3
"""
WordPress Backup/Restore Tool

This script can backup and restore a WordPress site, including files and database.
It uses SSH for file transfer and mysqldump for database operations.
"""

import argparse
import os
import sys
import tempfile
import zipfile
import datetime
import subprocess
import shutil
import re


def extract_db_credentials_from_wpconfig(ssh_user, ssh_host, ssh_key, wp_path, ssh_port=22):
    """Extract database credentials from wp-config.php file on the server."""
    print("Extracting database credentials from wp-config.php...")
    wp_config_path = f"{wp_path}/wp-config.php"
    
    # Command to extract database variables from wp-config.php
    ssh_cmd = [
        "ssh",
        "-i", ssh_key,
        "-p", str(ssh_port),
        f"{ssh_user}@{ssh_host}",
        f"grep -E \"DB_NAME|DB_USER|DB_PASSWORD|DB_HOST\" {wp_config_path}"
    ]
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
        config_lines = result.stdout.splitlines()
        
        # Initialize variables
        db_credentials = {
            'db_name': None,
            'db_user': None,
            'db_password': None,
            'db_host': 'localhost'  # Default value
        }
        
        # Parse each line to extract the values
        for line in config_lines:
            if 'DB_NAME' in line:
                match = re.search(r"define\(\s*['\"](DB_NAME)['\"]\s*,\s*['\"]([^'\"]+)['\"]", line)
                if match:
                    db_credentials['db_name'] = match.group(2)
            elif 'DB_USER' in line:
                match = re.search(r"define\(\s*['\"](DB_USER)['\"]\s*,\s*['\"]([^'\"]+)['\"]", line)
                if match:
                    db_credentials['db_user'] = match.group(2)
            elif 'DB_PASSWORD' in line:
                match = re.search(r"define\(\s*['\"](DB_PASSWORD)['\"]\s*,\s*['\"]([^'\"]+)['\"]", line)
                if match:
                    db_credentials['db_password'] = match.group(2)
            elif 'DB_HOST' in line:
                match = re.search(r"define\(\s*['\"](DB_HOST)['\"]\s*,\s*['\"]([^'\"]+)['\"]", line)
                if match:
                    db_credentials['db_host'] = match.group(2)
        
        # Verify all required credentials were found
        missing = [k for k, v in db_credentials.items() if v is None]
        if missing:
            raise ValueError(f"Missing database credentials in wp-config.php: {', '.join(missing)}")
            
        return db_credentials
    
    except subprocess.CalledProcessError as e:
        print(f"Error extracting WordPress database credentials: {e}")
        if e.stderr:
            print(f"Error details: {e.stderr}")
        raise ValueError("Failed to extract database credentials from wp-config.php")


def extract_db_credentials_from_local_wpconfig(local_wp_config_path):
    """Extract database credentials from a local wp-config.php file."""
    db_credentials = {
        'db_name': None,
        'db_user': None,
        'db_password': None,
        'db_host': 'localhost'
    }
    with open(local_wp_config_path) as f:
        for line in f:
            if 'DB_NAME' in line:
                match = re.search(r"define\(\s*['\"]DB_NAME['\"]\s*,\s*['\"]([^'\"]+)['\"]\)", line)
                if match:
                    db_credentials['db_name'] = match.group(1)
            elif 'DB_USER' in line:
                match = re.search(r"define\(\s*['\"]DB_USER['\"]\s*,\s*['\"]([^'\"]+)['\"]\)", line)
                if match:
                    db_credentials['db_user'] = match.group(1)
            elif 'DB_PASSWORD' in line:
                match = re.search(r"define\(\s*['\"]DB_PASSWORD['\"]\s*,\s*['\"]([^'\"]+)['\"]\)", line)
                if match:
                    db_credentials['db_password'] = match.group(1)
            elif 'DB_HOST' in line:
                match = re.search(r"define\(\s*['\"]DB_HOST['\"]\s*,\s*['\"]([^'\"]+)['\"]\)", line)
                if match:
                    db_credentials['db_host'] = match.group(1)
    missing = [k for k, v in db_credentials.items() if v is None]
    if missing:
        raise ValueError(f"Missing database credentials in local wp-config.php: {', '.join(missing)}")
    return db_credentials


def backup_site(args):
    """Backup WordPress files and database to a local zip file."""
    print(f"Starting backup of WordPress site at {args.ssh_host}...")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = args.output_file or f"wordpress_backup_{timestamp}.zip"
    
    # Extract database credentials from wp-config.php
    db_credentials = extract_db_credentials_from_wpconfig(
        args.ssh_user, args.ssh_host, args.ssh_key, args.wp_path, args.ssh_port
    )
    
    # Create a temporary directory for the backup
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create directory structure
        files_dir = os.path.join(temp_dir, "files")
        db_dir = os.path.join(temp_dir, "database")
        os.makedirs(files_dir, exist_ok=True)
        os.makedirs(db_dir, exist_ok=True)
        
        # Backup database
        db_name = db_credentials['db_name']
        db_file = os.path.join(db_dir, f"{db_name}.sql")
        print(f"Backing up database {db_name}...")
        ssh_cmd = [
            "ssh", 
            "-i", args.ssh_key,
            "-p", str(args.ssh_port),
            f"{args.ssh_user}@{args.ssh_host}",
            f"mysqldump --user={db_credentials['db_user']} --password='{db_credentials['db_password']}' --host={db_credentials['db_host']} {db_name}"
        ]
        
        with open(db_file, 'w') as f:
            subprocess.run(ssh_cmd, stdout=f, check=True)
        
        # Backup files
        print(f"Backing up WordPress files from {args.wp_path}...")
        rsync_cmd = [
            "rsync", 
            "-avz", 
            "-e", f"ssh -i {args.ssh_key} -p {args.ssh_port}",
            f"{args.ssh_user}@{args.ssh_host}:{args.wp_path}/",
            f"{files_dir}/"
        ]
        subprocess.run(rsync_cmd, check=True)
        
        # Create zip file
        print(f"Creating backup archive: {backup_filename}")
        with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add database dump
            for root, _, files in os.walk(db_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
            
            # Add WordPress files
            for root, _, files in os.walk(files_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
    
    print(f"Backup complete: {os.path.abspath(backup_filename)}")
    return True


def restore_site(args):
    """Restore WordPress files and database from a zip file."""
    print(f"Starting restoration of WordPress site to {args.ssh_host}...")
    
    if not os.path.exists(args.input_file):
        print(f"Error: Backup file {args.input_file} not found")
        return False
    
    # Create a temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract zip file
        print(f"Extracting backup archive: {args.input_file}")
        with zipfile.ZipFile(args.input_file, 'r') as zipf:
            zipf.extractall(temp_dir)
        
        # Extract database credentials from wp-config.php if we're not overwriting it
        try:
            db_credentials = extract_db_credentials_from_wpconfig(
                args.ssh_user, args.ssh_host, args.ssh_key, args.wp_path, args.ssh_port
            )
        except ValueError:
            # Attempt to get credentials from local wp-config in backup if no override
            if not args.db_credentials_override:
                local_wpconfig = os.path.join(temp_dir, "files", "wp-config.php")
                if os.path.exists(local_wpconfig):
                    print("Extracting database credentials from local wp-config.php in backup...")
                    db_credentials = extract_db_credentials_from_local_wpconfig(local_wpconfig)
                else:
                    print("Error: Could not extract database credentials and no wp-config.php in backup")
                    return False
            else:
                db_credentials = {
                    'db_name': args.db_name,
                    'db_user': args.db_user,
                    'db_password': args.db_password,
                    'db_host': args.db_host or 'localhost'
                }
        
        # Restore files
        files_dir = os.path.join(temp_dir, "files")
        if not os.path.exists(files_dir):
            print("Error: No files directory found in backup")
            return False
        
        print(f"Restoring WordPress files to {args.wp_path}...")
        rsync_cmd = [
            "rsync", 
            "-avz", 
            "--delete",
            "-e", f"ssh -i {args.ssh_key} -p {args.ssh_port}",
            f"{files_dir}/",
            f"{args.ssh_user}@{args.ssh_host}:{args.wp_path}/"
        ]
        subprocess.run(rsync_cmd, check=True)
        
        # Restore database
        db_name = db_credentials['db_name']
        db_file = os.path.join(temp_dir, "database", f"{db_name}.sql")
        
        # Check if we need to look for a differently named database file
        if not os.path.exists(db_file):
            # Try to find any .sql file in the database directory
            database_dir = os.path.join(temp_dir, "database")
            if os.path.exists(database_dir):
                sql_files = [f for f in os.listdir(database_dir) if f.endswith('.sql')]
                if sql_files:
                    db_file = os.path.join(database_dir, sql_files[0])
                    print(f"Using database dump file: {os.path.basename(db_file)}")
        
        if not os.path.exists(db_file):
            print(f"Error: Database dump for {db_name} not found in backup")
            return False
        
        print(f"Restoring database {db_name}...")
        # Create SQL to drop tables if they exist
        drop_tables_cmd = [
            "ssh", 
            "-i", args.ssh_key,
            "-p", str(args.ssh_port),
            f"{args.ssh_user}@{args.ssh_host}",
            f"mysql --user={db_credentials['db_user']} --password='{db_credentials['db_password']}' --host={db_credentials['db_host']} {db_name} -e \"SHOW TABLES\" | grep -v Tables_in | xargs -I{{}} echo \"DROP TABLE IF EXISTS {{}};\""
        ]
        
        drop_tables_result = subprocess.run(drop_tables_cmd, capture_output=True, text=True, check=False)
        if drop_tables_result.returncode == 0 and drop_tables_result.stdout:
            drop_sql = drop_tables_result.stdout
            print("Dropping existing tables...")
            subprocess.run([
                "ssh", 
                "-i", args.ssh_key,
                "-p", str(args.ssh_port),
                f"{args.ssh_user}@{args.ssh_host}",
                f"mysql --user={db_credentials['db_user']} --password='{db_credentials['db_password']}' --host={db_credentials['db_host']} {db_name} -e \"{drop_sql}\""
            ], check=True)
        
        # Import database
        cat_cmd = ["cat", db_file]
        ssh_cmd = [
            "ssh", 
            "-i", args.ssh_key,
            "-p", str(args.ssh_port),
            f"{args.ssh_user}@{args.ssh_host}",
            f"mysql --user={db_credentials['db_user']} --password='{db_credentials['db_password']}' --host={db_credentials['db_host']} {db_name}"
        ]
        
        cat_process = subprocess.Popen(cat_cmd, stdout=subprocess.PIPE)
        ssh_process = subprocess.Popen(ssh_cmd, stdin=cat_process.stdout, stdout=subprocess.PIPE)
        cat_process.stdout.close()  # Allow cat_process to receive SIGPIPE if ssh_process exits
        ssh_process.communicate()
    
    print("Restoration complete!")
    return True


def main():
    """Parse arguments and run backup or restore."""
    parser = argparse.ArgumentParser(description="WordPress Backup/Restore Tool")
    parser.add_argument("action", choices=["backup", "restore"], help="Action to perform")
    
    # SSH connection parameters
    parser.add_argument("--ssh-host", required=True, help="SSH hostname")
    parser.add_argument("--ssh-user", default="root", help="SSH username (default: root)")
    parser.add_argument("--ssh-key", required=True, help="Path to SSH private key file")
    parser.add_argument("--wp-path", required=True, help="WordPress installation path on the server")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22)")
    
    # Database parameters - now optional as they can be extracted from wp-config.php
    parser.add_argument("--db-name", help="MySQL database name (optional, extracted from wp-config.php)")
    parser.add_argument("--db-user", help="MySQL database user (optional, extracted from wp-config.php)")
    parser.add_argument("--db-password", help="MySQL database password (optional, extracted from wp-config.php)")
    parser.add_argument("--db-host", help="MySQL database host (optional, extracted from wp-config.php)")
    parser.add_argument("--db-credentials-override", action="store_true", 
                       help="Use provided database credentials instead of extracting from wp-config.php")
    
    # Backup specific options
    parser.add_argument("--output-file", help="Output backup filename (default: wordpress_backup_<timestamp>.zip)")
    
    # Restore specific options
    parser.add_argument("--input-file", help="Input backup filename for restoration")
    
    args = parser.parse_args()
    
    # Validate arguments based on action
    if args.action == "restore" and not args.input_file:
        parser.error("--input-file is required for restore action")
    
    # Ensure SSH key has correct permissions
    if os.path.exists(args.ssh_key):
        current_perms = os.stat(args.ssh_key).st_mode & 0o777
        if current_perms != 0o600:
            print(f"Warning: SSH key file {args.ssh_key} has incorrect permissions. Setting to 600.")
            os.chmod(args.ssh_key, 0o600)
    else:
        print(f"Error: SSH key file {args.ssh_key} not found")
        return 1
    
    # Execute requested action
    success = False
    if args.action == "backup":
        success = backup_site(args)
    elif args.action == "restore":
        success = restore_site(args)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
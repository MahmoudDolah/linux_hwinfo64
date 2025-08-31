import psutil
import platform
import subprocess
import os
import glob
import re
import logging
import time
import socket

try:
    import distro

    HAS_DISTRO = True
except ImportError:
    HAS_DISTRO = False


class SystemMonitor:
    def __init__(self):
        # Cache for GPU detection to avoid repeated subprocess calls
        self._gpu_detection_cache = {}
        self._gpu_detection_cache_time = 0
        self._gpu_detection_cache_ttl = 60  # Cache for 60 seconds

        self.gpu_type = self._detect_gpu_type()
        self._amd_gpu_device_path = (
            self._get_amd_gpu_path() if self.gpu_type == "amd" else None
        )

    def _get_amd_gpu_path(self):
        """
        Find the AMD GPU device path using globbing with caching.
        Returns the device path as a string, or None if not found.
        """
        current_time = time.time()

        # Check if we have a valid cached result
        if (
            current_time - self._gpu_detection_cache_time
            < self._gpu_detection_cache_ttl
            and "amd_gpu_path" in self._gpu_detection_cache
        ):
            return self._gpu_detection_cache["amd_gpu_path"]

        # Cache miss or expired - perform detection
        amd_gpu_path = self._perform_amd_gpu_path_detection()

        # Update cache
        self._gpu_detection_cache["amd_gpu_path"] = amd_gpu_path

        return amd_gpu_path

    def _perform_amd_gpu_path_detection(self):
        """Perform the actual AMD GPU path detection"""
        device_paths = glob.glob("/sys/class/drm/card*/device")
        for device_path in device_paths:
            vendor_file = os.path.join(device_path, "vendor")
            if os.path.exists(vendor_file):
                try:
                    with open(vendor_file, "r") as f:
                        vendor_id = f.read().strip()
                        # AMD vendor ID is 0x1002
                        if vendor_id == "0x1002":
                            return device_path
                except (IOError, ValueError):
                    continue
        return None

    def _detect_gpu_type(self):
        """Detect GPU type (NVIDIA, AMD, or None) with caching"""
        current_time = time.time()

        # Check if we have a valid cached result
        if (
            current_time - self._gpu_detection_cache_time
            < self._gpu_detection_cache_ttl
            and "gpu_type" in self._gpu_detection_cache
        ):
            return self._gpu_detection_cache["gpu_type"]

        # Cache miss or expired - perform detection
        gpu_type = self._perform_gpu_detection()

        # Update cache
        self._gpu_detection_cache["gpu_type"] = gpu_type
        self._gpu_detection_cache_time = current_time

        return gpu_type

    def _perform_gpu_detection(self):
        """Perform the actual GPU detection"""
        # Check for NVIDIA GPU
        try:
            subprocess.check_output(["nvidia-smi"])
            return "nvidia"
        except (subprocess.SubprocessError, FileNotFoundError):
            logging.debug("NVIDIA GPU not detected via nvidia-smi")

        # Check for AMD GPU
        try:
            # Check if any AMD GPU device exists using our new function
            amd_device_path = self._get_amd_gpu_path()
            if amd_device_path:
                return "amd"

            # Alternative check using lspci
            lspci_output = subprocess.check_output(["lspci"], universal_newlines=True)
            if "amd" in lspci_output.lower() and (
                "vga" in lspci_output.lower() or "display" in lspci_output.lower()
            ):
                return "amd"
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logging.debug(f"Error detecting AMD GPU: {e}")
        except IOError as e:
            logging.debug(f"IO error while detecting AMD GPU: {e}")

        logging.info("No supported GPU detected")
        return "none"

    def get_cpu_info(self):
        """Get CPU information"""
        cpu_info = {
            "usage_percent": psutil.cpu_percent(interval=0.1, percpu=True),
            "average_usage": psutil.cpu_percent(interval=0.1),
            "freq": psutil.cpu_freq(),
            "count": psutil.cpu_count(logical=True),
            "physical_count": psutil.cpu_count(logical=False),
            "temps": self._get_cpu_temps(),
            "name": self._get_cpu_name(),
        }
        return cpu_info

    def _get_cpu_name(self):
        """Get CPU model name"""
        if platform.system() == "Linux":
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except IOError as e:
                logging.warning(f"Could not read /proc/cpuinfo: {e}")
        return platform.processor()

    def _get_cpu_temps(self):
        """Get CPU temperatures if available"""
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            temp_data = psutil.sensors_temperatures()
            # Look for common CPU temperature sensors
            for chip, sensors in temp_data.items():
                if any(
                    x in chip.lower() for x in ["cpu", "coretemp", "k10temp", "ryzen"]
                ):
                    for sensor in sensors:
                        temps[sensor.label or chip] = sensor.current
        return temps

    def get_gpu_info(self):
        """Get GPU information"""
        if self.gpu_type == "nvidia":
            return self._get_nvidia_gpu_info()
        elif self.gpu_type == "amd":
            return self._get_amd_gpu_info()
        else:
            return {"status": "No supported GPU detected"}

    def _get_nvidia_gpu_info(self):
        """Get NVIDIA GPU information"""
        try:
            gpu_info = {}
            nvidia_smi = (
                subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw",
                        "--format=csv,noheader,nounits",
                    ]
                )
                .decode("utf-8")
                .strip()
            )

            name, temp, gpu_util, mem_util, mem_used, mem_total, power = (
                nvidia_smi.split(",")
            )

            gpu_info = {
                "type": "NVIDIA",
                "name": name.strip(),
                "temperature": float(temp.strip()),
                "gpu_utilization": float(gpu_util.strip()),
                "memory_utilization": float(mem_util.strip()),
                "memory_used": float(mem_used.strip()),
                "memory_total": float(mem_total.strip()),
                "power_draw": float(power.strip()) if power.strip() else 0,
            }

            return gpu_info
        except Exception as e:
            return {"status": f"Error fetching NVIDIA GPU info: {str(e)}"}

    def _get_amd_gpu_info(self):
        """Get AMD GPU information"""
        try:
            gpu_info = {"type": "AMD"}

            # Try to get GPU name
            try:
                lspci_output = subprocess.check_output(
                    "lspci | grep -E 'VGA|Display|3D' | grep -i amd",
                    shell=True,
                    universal_newlines=True,
                )
                if lspci_output:
                    # Extract the GPU name from lspci output
                    name_match = lspci_output.split(":")[-1].strip()
                    gpu_info["name"] = name_match
                else:
                    gpu_info["name"] = "AMD GPU"
            except subprocess.SubprocessError as e:
                logging.warning(f"Failed to get AMD GPU name via lspci: {e}")
                gpu_info["name"] = "AMD GPU"

            # Try to read temperature
            try:
                # Different AMD cards might use different paths
                temp_paths = []
                if self._amd_gpu_device_path:
                    temp_paths = [
                        os.path.join(
                            self._amd_gpu_device_path, "hwmon/hwmon*/temp1_input"
                        ),
                        "/sys/class/hwmon/hwmon*/temp1_input",
                    ]

                temp_value = None
                for path_pattern in temp_paths:
                    matching_paths = glob.glob(path_pattern)
                    if matching_paths:
                        with open(matching_paths[0], "r") as f:
                            temp_value = (
                                int(f.read().strip()) / 1000
                            )  # Convert from millidegrees to degrees
                            break

                if temp_value is not None:
                    gpu_info["temperature"] = temp_value
                else:
                    logging.debug("No temperature file found for AMD GPU")
            except (IOError, ValueError) as e:
                logging.warning(f"Failed to read AMD GPU temperature: {e}")

            # Try to get memory info using rocm-smi if available
            try:
                rocm_output = subprocess.check_output(
                    ["rocm-smi", "--showmeminfo", "vram"], universal_newlines=True
                )

                total_memory_match = re.search(
                    r"VRAM Total Memory \(B\): (\d+)", rocm_output
                )
                used_memory_match = re.search(
                    r"VRAM Total Used Memory \(B\): (\d+)", rocm_output
                )

                total_memory_mb = 0
                used_memory_mb = 0

                if total_memory_match and used_memory_match:
                    total_memory_bytes = int(total_memory_match.group(1))
                    used_memory_bytes = int(used_memory_match.group(1))

                    # Convert to MB for easier reading
                    total_memory_mb = total_memory_bytes / (1024 * 1024)
                    used_memory_mb = used_memory_bytes / (1024 * 1024)

                if total_memory_mb > 0 and used_memory_mb > 0:
                    gpu_info["memory_used"] = used_memory_mb
                    gpu_info["memory_total"] = total_memory_mb
                    gpu_info["memory_utilization"] = (
                        gpu_info["memory_used"] / gpu_info["memory_total"]
                    ) * 100
                else:
                    logging.debug("Memory information not found in rocm-smi output")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logging.debug(f"rocm-smi not available or failed: {e}")

            # Try to read GPU utilization
            try:
                gpu_busy_path = self._get_gpu_busy_path()
                if gpu_busy_path is not None:
                    with open(gpu_busy_path, "r") as f:
                        gpu_info["gpu_utilization"] = float(f.read().strip())
                else:
                    logging.debug("GPU utilization file not found for AMD GPU")
            except AttributeError as e:
                logging.error(f"Method _get_gpu_busy_path not found: {e}")
            except (IOError, ValueError) as e:
                logging.warning(f"Failed to read AMD GPU utilization: {e}")
            except Exception as e:
                logging.error(f"Unexpected error in GPU utilization detection: {e}")

            # If we couldn't get any dynamic data, at least return the static info
            if len(gpu_info) <= 2:  # Only type and name
                gpu_info["status"] = "Limited AMD GPU info available"
                logging.warning("Limited AMD GPU information available")

            return gpu_info
        except Exception as e:
            logging.error(f"Error fetching AMD GPU info: {e}")
            return {"status": f"Error fetching AMD GPU info: {str(e)}"}

    def _get_gpu_busy_path(self):
        """
        Find the first available GPU busy percentage file and return its path with caching.
        Returns the file path as a string, or None if not found.
        """
        current_time = time.time()

        # Check if we have a valid cached result
        if (
            current_time - self._gpu_detection_cache_time
            < self._gpu_detection_cache_ttl
            and "gpu_busy_path" in self._gpu_detection_cache
        ):
            return self._gpu_detection_cache["gpu_busy_path"]

        # Cache miss or expired - perform detection
        gpu_busy_path = self._perform_gpu_busy_path_detection()

        # Update cache
        self._gpu_detection_cache["gpu_busy_path"] = gpu_busy_path

        return gpu_busy_path

    def _perform_gpu_busy_path_detection(self):
        """Perform the actual GPU busy path detection"""
        if self._amd_gpu_device_path:
            gpu_busy_file = os.path.join(self._amd_gpu_device_path, "gpu_busy_percent")
            if os.path.exists(gpu_busy_file) and os.access(gpu_busy_file, os.R_OK):
                return gpu_busy_file

        # Fallback to glob search for other card numbers
        gpu_files = glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")
        for gpu_file in gpu_files:
            try:
                if os.access(gpu_file, os.R_OK):
                    return gpu_file
            except PermissionError:
                logging.warning(f"Permission denied accessing {gpu_file}")
                continue
            except FileNotFoundError:
                logging.debug(f"GPU file not found: {gpu_file}")
                continue
            except Exception as e:
                logging.error(f"Unexpected error accessing {gpu_file}: {e}")
                continue
        return None

    def get_memory_info(self):
        """Get system memory information"""
        memory = psutil.virtual_memory()
        return {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free,
        }

    def get_disk_io_info(self):
        """Get disk I/O information"""
        try:
            # Get disk I/O counters
            disk_io = psutil.disk_io_counters()
            if disk_io is None:
                return {"status": "Disk I/O information not available"}

            # Get per-disk statistics
            disk_io_per_disk = psutil.disk_io_counters(perdisk=True)

            # Get disk usage for mounted filesystems
            disk_usage = {}
            partitions = psutil.disk_partitions()
            for partition in partitions:
                try:
                    if partition.fstype:  # Skip virtual filesystems
                        usage = psutil.disk_usage(partition.mountpoint)
                        disk_usage[partition.device] = {
                            "mountpoint": partition.mountpoint,
                            "fstype": partition.fstype,
                            "total": usage.total,
                            "used": usage.used,
                            "free": usage.free,
                            "percent": (usage.used / usage.total) * 100
                            if usage.total > 0
                            else 0,
                        }
                except (PermissionError, OSError):
                    # Skip filesystems we can't access
                    continue

            disk_info = {
                "total": {
                    "read_count": disk_io.read_count,
                    "write_count": disk_io.write_count,
                    "read_bytes": disk_io.read_bytes,
                    "write_bytes": disk_io.write_bytes,
                    "read_time": disk_io.read_time,
                    "write_time": disk_io.write_time,
                    "read_merged_count": getattr(disk_io, "read_merged_count", 0),
                    "write_merged_count": getattr(disk_io, "write_merged_count", 0),
                    "busy_time": getattr(disk_io, "busy_time", 0),
                },
                "per_disk": {},
                "usage": disk_usage,
            }

            # Add per-disk I/O statistics
            for disk_name, disk_stats in disk_io_per_disk.items():
                disk_info["per_disk"][disk_name] = {
                    "read_count": disk_stats.read_count,
                    "write_count": disk_stats.write_count,
                    "read_bytes": disk_stats.read_bytes,
                    "write_bytes": disk_stats.write_bytes,
                    "read_time": disk_stats.read_time,
                    "write_time": disk_stats.write_time,
                    "read_merged_count": getattr(disk_stats, "read_merged_count", 0),
                    "write_merged_count": getattr(disk_stats, "write_merged_count", 0),
                    "busy_time": getattr(disk_stats, "busy_time", 0),
                }

            return disk_info

        except Exception as e:
            logging.error(f"Error fetching disk I/O info: {e}")
            return {"status": f"Error fetching disk I/O info: {str(e)}"}

    def get_system_info(self):
        """Get comprehensive system information for neofetch-like display"""
        try:
            # Get OS information
            if HAS_DISTRO:
                os_name = distro.name()
                os_version = distro.version()
                os_codename = distro.codename()
            else:
                # Fallback to reading /etc/os-release
                try:
                    with open("/etc/os-release", "r") as f:
                        os_release = {}
                        for line in f:
                            if "=" in line:
                                key, value = line.strip().split("=", 1)
                                os_release[key] = value.strip('"')
                        os_name = os_release.get("NAME", "Linux")
                        os_version = os_release.get("VERSION", "Unknown")
                        os_codename = os_release.get("VERSION_CODENAME", "")
                except (IOError, ValueError, KeyError):
                    os_name = platform.system()
                    os_version = platform.release()
                    os_codename = ""

            os_info = {
                "name": os_name,
                "version": os_version,
                "codename": os_codename,
                "kernel": platform.release(),
                "architecture": platform.machine(),
                "hostname": socket.gethostname(),
                "username": os.getenv("USER", "unknown"),
            }

            # Get uptime
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.read().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)

                if days > 0:
                    uptime_str = f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    uptime_str = f"{hours}h {minutes}m"
                else:
                    uptime_str = f"{minutes}m"

                os_info["uptime"] = uptime_str

            # Get shell information
            shell = os.getenv("SHELL", "unknown")
            if shell != "unknown":
                shell = os.path.basename(shell)
            os_info["shell"] = shell

            # Get desktop environment/window manager
            desktop = (
                os.getenv("XDG_CURRENT_DESKTOP")
                or os.getenv("DESKTOP_SESSION")
                or "unknown"
            )
            os_info["desktop"] = desktop

            # Get terminal information
            terminal = os.getenv("TERM") or "unknown"
            os_info["terminal"] = terminal

            return os_info

        except Exception as e:
            logging.error(f"Error fetching system info: {e}")
            return {"status": f"Error fetching system info: {str(e)}"}

    def display_neofetch_info(self):
        """Display system information in neofetch-like format"""
        try:
            system_info = self.get_system_info()
            cpu_info = self.get_cpu_info()
            gpu_info = self.get_gpu_info()
            memory_info = self.get_memory_info()

            # Simple ASCII art (optional)
            ascii_art = [
                "    .---.",
                "   /     \\",
                "  | () () |",
                "   \\  ^  /",
                "    |||||",
                "    |||||",
            ]

            # Print header with hostname
            print(f"\n{system_info['username']}@{system_info['hostname']}")
            print(
                "-" * (len(system_info["username"]) + len(system_info["hostname"]) + 1)
            )

            # Display system information with ASCII art
            info_lines = [
                f"OS: {system_info['name']} {system_info['version']}",
                f"Kernel: {system_info['kernel']}",
                f"Uptime: {system_info['uptime']}",
                f"Shell: {system_info['shell']}",
                f"Desktop: {system_info['desktop']}",
                f"Terminal: {system_info['terminal']}",
                f"CPU: {cpu_info['name']}",
                f"Cores: {cpu_info['physical_count']} physical, {cpu_info['count']} logical",
            ]

            # Add GPU info if available
            if "status" not in gpu_info:
                info_lines.append(f"GPU: {gpu_info['name']}")

            # Add memory info
            mem_used_gb = memory_info["used"] / (1024**3)
            mem_total_gb = memory_info["total"] / (1024**3)
            info_lines.append(
                f"Memory: {mem_used_gb:.1f}GB / {mem_total_gb:.1f}GB ({memory_info['percent']:.1f}%)"
            )

            # Display with ASCII art on the left
            max_lines = max(len(ascii_art), len(info_lines))

            for i in range(max_lines):
                ascii_part = ascii_art[i] if i < len(ascii_art) else " " * 12
                info_part = info_lines[i] if i < len(info_lines) else ""
                print(f"{ascii_part}   {info_part}")

            print()  # Extra newline at the end

        except Exception as e:
            logging.error(f"Error displaying neofetch info: {e}")
            print(f"Error displaying system info: {e}")

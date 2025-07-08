import psutil
import platform
import subprocess
import os
import glob
import re
import logging


class SystemMonitor:
    def __init__(self):
        self.gpu_type = self._detect_gpu_type()
        self._amd_gpu_device_path = self._get_amd_gpu_path() if self.gpu_type == "amd" else None

    def _get_amd_gpu_path(self):
        """
        Find the AMD GPU device path using globbing.
        Returns the device path as a string, or None if not found.
        """
        device_paths = glob.glob('/sys/class/drm/card*/device')
        for device_path in device_paths:
            vendor_file = os.path.join(device_path, 'vendor')
            if os.path.exists(vendor_file):
                try:
                    with open(vendor_file, 'r') as f:
                        vendor_id = f.read().strip()
                        # AMD vendor ID is 0x1002
                        if vendor_id == "0x1002":
                            return device_path
                except (IOError, ValueError):
                    continue
        return None

    def _detect_gpu_type(self):
        """Detect GPU type (NVIDIA, AMD, or None)"""
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
                        os.path.join(self._amd_gpu_device_path, "hwmon/hwmon*/temp1_input"),
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
                    ["rocm-smi", "--showmeminfo","vram"], universal_newlines=True
                )

                total_memory_match = re.search(r'VRAM Total Memory \(B\): (\d+)', rocm_output)
                used_memory_match = re.search(r'VRAM Total Used Memory \(B\): (\d+)', rocm_output)

                if total_memory_match and used_memory_match:
                    total_memory_bytes = int(total_memory_match.group(1))
                    used_memory_bytes = int(used_memory_match.group(1))

                    # Convert to MB for easier reading
                    total_memory_mb = total_memory_bytes / (1024 * 1024)
                    used_memory_mb = used_memory_bytes / (1024 * 1024)

                if total_memory_mb and used_memory_mb:
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
            except (IOError, ValueError) as e:
                logging.warning(f"Failed to read AMD GPU utilization: {e}")

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
        Find the first available GPU busy percentage file and return its path.
        Returns the file path as a string, or None if not found.
        """
        if self._amd_gpu_device_path:
            gpu_busy_file = os.path.join(self._amd_gpu_device_path, "gpu_busy_percent")
            if os.path.exists(gpu_busy_file) and os.access(gpu_busy_file, os.R_OK):
                return gpu_busy_file

        # Fallback to glob search for other card numbers
        gpu_files = glob.glob('/sys/class/drm/card*/device/gpu_busy_percent')
        for gpu_file in gpu_files:
            try:
                if os.access(gpu_file, os.R_OK):
                    return gpu_file
            except (IOError, ValueError) as e:
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

import time
import curses
import logging
import argparse
import collections
from datetime import datetime
from system_monitor import SystemMonitor


def safe_addstr(stdscr, y, x, text, attr=curses.A_NORMAL):
    """Safely add string to screen with bounds checking"""
    try:
        max_y, max_x = stdscr.getmaxyx()
        if y >= 0 and y < max_y and x >= 0 and x < max_x:
            # Truncate text if it would exceed screen width
            available_width = max_x - x
            if len(text) > available_width:
                text = text[:available_width]
            stdscr.addstr(y, x, text, attr)
    except curses.error:
        # Silently ignore curses errors (terminal too small, etc.)
        pass


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="hw_monitor.log",
    filemode="a",
)


def draw_graph(
    stdscr, y_start, x_start, width, height, data, title, color_pair, y_max=100
):
    """Draw a line graph on the screen

    Args:
        stdscr: Curses window object
        y_start, x_start: Starting coordinates for the graph
        width, height: Dimensions of the graph
        data: List of data points to plot
        title: Graph title
        color_pair: Curses color pair for the graph line
        y_max: Maximum value for y-axis (default: 100%)
    """
    # Draw title
    stdscr.addstr(y_start, x_start, title, curses.A_BOLD)

    # Draw border
    for i in range(height):
        stdscr.addstr(y_start + 1 + i, x_start, "|")
        stdscr.addstr(y_start + 1 + i, x_start + width + 1, "|")

    for i in range(width + 2):
        stdscr.addstr(y_start + height + 1, x_start + i, "-")

    # Draw y-axis labels
    stdscr.addstr(y_start + 1, x_start - 4, f"{y_max:3d}%")
    stdscr.addstr(y_start + height // 2, x_start - 4, f"{y_max // 2:3d}%")
    stdscr.addstr(y_start + height, x_start - 4, "  0%")

    # Plot data points
    data_len = len(data)
    for i in range(min(width, data_len - 1)):
        x1 = i
        y1 = height - int((data[data_len - 1 - i] / y_max) * height)
        x2 = i + 1
        y2 = height - int((data[data_len - 2 - i] / y_max) * height)

        # Ensure y values are within range
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height - 1, y2))

        # Draw line segment
        if x1 == x2:
            start_y = min(y1, y2)
            end_y = max(y1, y2)
            for y in range(start_y, end_y + 1):
                stdscr.addstr(y_start + 1 + y, x_start + 1 + x1, "│", color_pair)
        else:
            if y1 < y2:
                char = "╱"
            elif y1 > y2:
                char = "╲"
            else:
                char = "─"
            stdscr.addstr(y_start + 1 + y1, x_start + 1 + x1, char, color_pair)


def display_monitor_graph(stdscr):
    """Display system metrics as graphs over time"""
    monitor = SystemMonitor()

    # Set up colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)

    curses.curs_set(0)  # Hide cursor
    stdscr.timeout(1000)  # Set refresh rate to 1 second

    # Check minimum terminal size
    min_height, min_width = 35, 100
    max_y, max_x = stdscr.getmaxyx()
    if max_y < min_height or max_x < min_width:
        safe_addstr(
            stdscr,
            0,
            0,
            f"Terminal too small! Need at least {min_width}x{min_height}, got {max_x}x{max_y}",
        )
        safe_addstr(stdscr, 1, 0, "Press 'q' to quit")
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key == ord("q"):
                return

    # Store historical data
    history_length = 120  # 2 minutes of data at 1s intervals
    cpu_history = collections.deque([0] * history_length, maxlen=history_length)
    memory_history = collections.deque([0] * history_length, maxlen=history_length)
    gpu_util_history = collections.deque([0] * history_length, maxlen=history_length)
    gpu_memory_history = collections.deque([0] * history_length, maxlen=history_length)
    disk_usage_history = collections.deque([0] * history_length, maxlen=history_length)

    # Determine terminal size
    max_y, max_x = stdscr.getmaxyx()
    graph_width = min(max_x - 14, 100)  # Max width or 100 chars

    while True:
        # Get system information
        cpu_info = monitor.get_cpu_info()
        gpu_info = monitor.get_gpu_info()
        memory_info = monitor.get_memory_info()
        disk_info = monitor.get_disk_io_info()

        # Update history
        cpu_history.appendleft(cpu_info["average_usage"])
        memory_history.appendleft(memory_info["percent"])

        # Track disk usage (use the first disk's usage percentage)
        if "status" not in disk_info and disk_info["usage"]:
            first_disk_usage = next(iter(disk_info["usage"].values()))["percent"]
            disk_usage_history.appendleft(first_disk_usage)
        else:
            disk_usage_history.appendleft(0)

        if "gpu_utilization" in gpu_info:
            gpu_util_history.appendleft(gpu_info["gpu_utilization"])
        else:
            gpu_util_history.appendleft(0)

        if "memory_utilization" in gpu_info:
            gpu_memory_history.appendleft(gpu_info["memory_utilization"])
        elif (
            "memory_used" in gpu_info
            and "memory_total" in gpu_info
            and gpu_info["memory_total"] > 0
        ):
            gpu_memory_history.appendleft(
                (gpu_info["memory_used"] / gpu_info["memory_total"]) * 100
            )
        else:
            gpu_memory_history.appendleft(0)

        # Clear screen
        stdscr.clear()

        # Display title and time
        now = datetime.now().strftime("%H:%M:%S")
        stdscr.addstr(
            0,
            0,
            f"Linux Hardware Monitor (Graph Mode) - {now} (Press 'q' to quit)",
            curses.A_BOLD,
        )

        # Display system info
        stdscr.addstr(
            1,
            0,
            f"CPU: {cpu_info['name']} | "
            + f"Cores: {cpu_info['physical_count']} Physical, {cpu_info['count']} Logical",
        )

        if "status" not in gpu_info:
            gpu_name = gpu_info.get("name", "Unknown GPU")
            gpu_temp = (
                f" | Temp: {gpu_info.get('temperature', 0):.1f}°C"
                if "temperature" in gpu_info
                else ""
            )
            safe_addstr(stdscr, 2, 0, f"GPU: {gpu_name}{gpu_temp}")
        else:
            safe_addstr(stdscr, 2, 0, f"GPU: {gpu_info['status']}")

        # Draw CPU usage graph
        draw_graph(
            stdscr,
            4,
            5,
            graph_width,
            8,
            cpu_history,
            "CPU Usage (%) - Last 2 Minutes",
            curses.color_pair(1),
        )

        # Draw Memory usage graph
        draw_graph(
            stdscr,
            15,
            5,
            graph_width,
            6,
            memory_history,
            "Memory Usage (%) - Last 2 Minutes",
            curses.color_pair(4),
        )

        # Draw GPU graphs if available
        if "status" not in gpu_info:
            gpu_y_start = 24

            # GPU utilization graph
            if "gpu_utilization" in gpu_info:
                draw_graph(
                    stdscr,
                    gpu_y_start,
                    5,
                    graph_width,
                    6,
                    gpu_util_history,
                    "GPU Utilization (%) - Last 2 Minutes",
                    curses.color_pair(5),
                )
                gpu_y_start += 9

            # GPU memory graph
            if "memory_used" in gpu_info and "memory_total" in gpu_info:
                draw_graph(
                    stdscr,
                    gpu_y_start,
                    5,
                    graph_width,
                    6,
                    gpu_memory_history,
                    "GPU Memory Usage (%) - Last 2 Minutes",
                    curses.color_pair(6),
                )

        # Draw disk usage graph
        disk_y_start = 24
        if "status" not in gpu_info:
            if "gpu_utilization" in gpu_info:
                disk_y_start += 9
            if "memory_used" in gpu_info and "memory_total" in gpu_info:
                disk_y_start += 9

        draw_graph(
            stdscr,
            disk_y_start,
            5,
            graph_width,
            6,
            disk_usage_history,
            "Disk Usage (%) - Last 2 Minutes",
            curses.color_pair(7),
        )

        # Refresh screen
        stdscr.refresh()

        # Check for key press
        key = stdscr.getch()
        if key == ord("q"):
            break


def display_monitor(stdscr):
    monitor = SystemMonitor()

    # Set up colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)

    curses.curs_set(0)  # Hide cursor
    stdscr.timeout(1000)  # Set getch() timeout to 1 second

    # Check minimum terminal size
    min_height, min_width = 25, 80
    max_y, max_x = stdscr.getmaxyx()
    if max_y < min_height or max_x < min_width:
        safe_addstr(
            stdscr,
            0,
            0,
            f"Terminal too small! Need at least {min_width}x{min_height}, got {max_x}x{max_y}",
        )
        safe_addstr(stdscr, 1, 0, "Press 'q' to quit")
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key == ord("q"):
                return

    while True:
        stdscr.clear()

        # Display time
        now = datetime.now().strftime("%H:%M:%S")
        safe_addstr(
            stdscr,
            0,
            0,
            f"Linux Hardware Monitor - {now} (Press 'q' to quit)",
            curses.A_BOLD,
        )

        # Get system information
        cpu_info = monitor.get_cpu_info()
        gpu_info = monitor.get_gpu_info()
        memory_info = monitor.get_memory_info()
        disk_info = monitor.get_disk_io_info()
        network_info = monitor.get_network_info()

        # Display CPU information
        stdscr.addstr(2, 0, "CPU INFORMATION", curses.A_BOLD)
        safe_addstr(stdscr, 3, 0, f"Model: {cpu_info['name']}")
        stdscr.addstr(
            4,
            0,
            f"Cores: {cpu_info['physical_count']} Physical, {cpu_info['count']} Logical",
        )

        if cpu_info["freq"]:
            current_freq = cpu_info["freq"].current
            max_freq = cpu_info["freq"].max if cpu_info["freq"].max else current_freq
            stdscr.addstr(
                5, 0, f"Frequency: {current_freq:.2f} MHz / {max_freq:.2f} MHz"
            )

        # Display CPU usage per core
        stdscr.addstr(7, 0, "CPU Usage per Core:")
        for i, usage in enumerate(cpu_info["usage_percent"]):
            y_pos = 8 + i
            bar_length = int(usage / 2)  # Scale to fit terminal

            # Color based on usage
            if usage < 60:
                color = curses.color_pair(1)  # Green
            elif usage < 85:
                color = curses.color_pair(2)  # Yellow
            else:
                color = curses.color_pair(3)  # Red

            stdscr.addstr(y_pos, 0, f"Core {i}: {usage:5.1f}% [")
            stdscr.addstr(y_pos, 15, "#" * bar_length, color)
            stdscr.addstr(y_pos, 15 + bar_length, " " * (50 - bar_length))
            stdscr.addstr(y_pos, 65, "]")

        # Display CPU temperature
        y_pos = 8 + len(cpu_info["usage_percent"]) + 1
        stdscr.addstr(y_pos, 0, "CPU Temperatures:")
        temp_y = y_pos + 1

        if cpu_info["temps"]:
            for sensor, temp in cpu_info["temps"].items():
                if temp < 60:
                    color = curses.color_pair(1)  # Green
                elif temp < 80:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                safe_addstr(stdscr, temp_y, 0, f"{sensor}: ", curses.A_BOLD)
                safe_addstr(stdscr, temp_y, 20, f"{temp:.1f}°C", color)
                temp_y += 1
        else:
            stdscr.addstr(temp_y, 0, "Temperature data not available")
            temp_y += 1

        # Display GPU information
        gpu_y = temp_y + 1
        stdscr.addstr(gpu_y, 0, "GPU INFORMATION", curses.A_BOLD)
        gpu_y += 1

        if "status" in gpu_info:
            stdscr.addstr(gpu_y, 0, gpu_info["status"])
            gpu_y += 1
        else:
            gpu_type = gpu_info.get("type", "Unknown")
            stdscr.addstr(gpu_y, 0, f"Type: {gpu_type}")
            gpu_y += 1

            safe_addstr(stdscr, gpu_y, 0, f"Model: {gpu_info['name']}")
            gpu_y += 1

            # Temperature if available
            if "temperature" in gpu_info:
                temp = gpu_info["temperature"]
                if temp < 60:
                    color = curses.color_pair(1)  # Green
                elif temp < 80:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(gpu_y, 0, "Temperature: ", curses.A_BOLD)
                stdscr.addstr(gpu_y, 13, f"{temp:.1f}°C", color)
                gpu_y += 1

            # GPU Utilization if available
            if "gpu_utilization" in gpu_info:
                util = gpu_info["gpu_utilization"]
                bar_length = int(util / 2)
                if util < 60:
                    color = curses.color_pair(1)  # Green
                elif util < 85:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(gpu_y, 0, f"GPU Usage: {util:5.1f}% [")
                stdscr.addstr(gpu_y, 16, "#" * bar_length, color)
                stdscr.addstr(gpu_y, 16 + bar_length, " " * (50 - bar_length))
                stdscr.addstr(gpu_y, 66, "]")
                gpu_y += 1

            # Memory if available
            if "memory_used" in gpu_info and "memory_total" in gpu_info:
                mem_used = gpu_info["memory_used"]
                mem_total = gpu_info["memory_total"]
                mem_percent = (mem_used / mem_total) * 100 if mem_total > 0 else 0
                bar_length = int(mem_percent / 2)

                if mem_percent < 60:
                    color = curses.color_pair(1)  # Green
                elif mem_percent < 85:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red

                stdscr.addstr(
                    gpu_y,
                    0,
                    f"VRAM: {mem_used:.0f}MB / {mem_total:.0f}MB [{mem_percent:5.1f}%] [",
                )
                stdscr.addstr(gpu_y, 38, "#" * bar_length, color)
                stdscr.addstr(gpu_y, 38 + bar_length, " " * (50 - bar_length))
                stdscr.addstr(gpu_y, 88, "]")
                gpu_y += 1

            # Power draw if available
            if "power_draw" in gpu_info and gpu_info["power_draw"] > 0:
                stdscr.addstr(gpu_y, 0, f"Power Draw: {gpu_info['power_draw']:.2f}W")
                gpu_y += 1

        # Display system memory
        mem_y = gpu_y + 1
        stdscr.addstr(mem_y, 0, "SYSTEM MEMORY", curses.A_BOLD)
        mem_y += 1

        mem_used = memory_info["used"] / (1024**3)  # Convert to GB
        mem_total = memory_info["total"] / (1024**3)  # Convert to GB
        mem_percent = memory_info["percent"]
        bar_length = int(mem_percent / 2)

        if mem_percent < 60:
            color = curses.color_pair(1)  # Green
        elif mem_percent < 85:
            color = curses.color_pair(2)  # Yellow
        else:
            color = curses.color_pair(3)  # Red

        stdscr.addstr(
            mem_y,
            0,
            f"RAM: {mem_used:.1f}GB / {mem_total:.1f}GB [{mem_percent:5.1f}%] [",
        )
        stdscr.addstr(mem_y, 36, "#" * bar_length, color)
        stdscr.addstr(mem_y, 36 + bar_length, " " * (50 - bar_length))
        stdscr.addstr(mem_y, 86, "]")

        # Display disk I/O information
        disk_y = mem_y + 2
        stdscr.addstr(disk_y, 0, "DISK I/O", curses.A_BOLD)
        disk_y += 1

        if "status" not in disk_info:
            # Display total disk I/O
            total_io = disk_info["total"]
            read_mb = total_io["read_bytes"] / (1024**2)
            write_mb = total_io["write_bytes"] / (1024**2)

            stdscr.addstr(
                disk_y,
                0,
                f"Total Read: {read_mb:.1f} MB ({total_io['read_count']} ops)",
            )
            disk_y += 1
            stdscr.addstr(
                disk_y,
                0,
                f"Total Write: {write_mb:.1f} MB ({total_io['write_count']} ops)",
            )
            disk_y += 1

            # Display disk usage for main filesystems
            if disk_info["usage"]:
                stdscr.addstr(disk_y, 0, "Disk Usage:")
                disk_y += 1

                # Show only the first 3 disks to avoid screen overflow
                for i, (device, usage) in enumerate(
                    list(disk_info["usage"].items())[:3]
                ):
                    if usage["total"] > 0:
                        used_gb = usage["used"] / (1024**3)
                        total_gb = usage["total"] / (1024**3)
                        percent = usage["percent"]

                        # Color based on usage
                        if percent < 80:
                            color = curses.color_pair(1)  # Green
                        elif percent < 95:
                            color = curses.color_pair(2)  # Yellow
                        else:
                            color = curses.color_pair(3)  # Red

                        bar_length = int(percent / 2)
                        device_name = device.split("/")[-1][
                            :8
                        ]  # Show only device name, truncated

                        safe_addstr(
                            stdscr,
                            disk_y,
                            0,
                            f"{device_name}: {used_gb:.1f}GB / {total_gb:.1f}GB [{percent:5.1f}%] [",
                        )
                        stdscr.addstr(disk_y, 36, "#" * bar_length, color)
                        stdscr.addstr(disk_y, 36 + bar_length, " " * (50 - bar_length))
                        stdscr.addstr(disk_y, 86, "]")
                        disk_y += 1
        else:
            safe_addstr(stdscr, disk_y, 0, f"Status: {disk_info['status']}")

        # Display network information
        net_y = disk_y + 2
        stdscr.addstr(net_y, 0, "NETWORK", curses.A_BOLD)
        net_y += 1

        if "error" not in network_info:
            # Display total bandwidth
            total_sent_mb = network_info["total_bytes_sent_per_sec"] / (1024**2)
            total_recv_mb = network_info["total_bytes_recv_per_sec"] / (1024**2)

            safe_addstr(stdscr, net_y, 0, f"Total Upload: {total_sent_mb:.2f} MB/s")
            net_y += 1
            safe_addstr(stdscr, net_y, 0, f"Total Download: {total_recv_mb:.2f} MB/s")
            net_y += 1

            # Display active interfaces
            active_interfaces = [
                name
                for name, info in network_info["interfaces"].items()
                if info["status"] == "up"
            ]

            if active_interfaces:
                safe_addstr(stdscr, net_y, 0, "Active Interfaces:")
                net_y += 1

                # Show first 3 active interfaces to avoid screen overflow
                for interface_name in active_interfaces[:3]:
                    interface = network_info["interfaces"][interface_name]

                    sent_kb = interface["bytes_sent_per_sec"] / 1024
                    recv_kb = interface["bytes_recv_per_sec"] / 1024

                    # Determine color based on activity
                    if sent_kb > 100 or recv_kb > 100:  # >100 KB/s
                        color = curses.color_pair(2)  # Yellow (active)
                    elif sent_kb > 10 or recv_kb > 10:  # >10 KB/s
                        color = curses.color_pair(1)  # Green (moderate)
                    else:
                        color = curses.A_NORMAL  # Normal (low activity)

                    safe_addstr(
                        stdscr,
                        net_y,
                        0,
                        f"{interface_name}: ↑{sent_kb:.1f} KB/s ↓{recv_kb:.1f} KB/s",
                        color,
                    )
                    net_y += 1
            else:
                safe_addstr(stdscr, net_y, 0, "No active network interfaces")
        else:
            safe_addstr(stdscr, net_y, 0, f"Network Error: {network_info['error']}")

        # Refresh the screen
        stdscr.refresh()

        # Check for quit
        key = stdscr.getch()
        if key == ord("q"):
            break


def main():
    parser = argparse.ArgumentParser(description="Linux Hardware Monitor")
    parser.add_argument(
        "--graph", "-g", action="store_true", help="Show graphical display mode"
    )
    parser.add_argument(
        "--record",
        "-r",
        action="store_true",
        help="Record metrics to a CSV file for later analysis",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="hw_metrics.csv",
        help="Output CSV file when using --record",
    )
    parser.add_argument(
        "--neofetch",
        "-n",
        action="store_true",
        help="Show system information in neofetch-like format",
    )
    args = parser.parse_args()

    try:
        if args.neofetch:
            # Display neofetch-like system information
            monitor = SystemMonitor()
            monitor.display_neofetch_info()
        elif args.record:
            # Setup for CSV recording
            import csv

            monitor = SystemMonitor()
            header = [
                "timestamp",
                "cpu_usage",
                "mem_usage",
                "mem_used_gb",
                "mem_total_gb",
            ]

            # Add GPU fields if available
            gpu_info = monitor.get_gpu_info()
            has_gpu = "status" not in gpu_info
            if has_gpu:
                header.extend(["gpu_util", "gpu_mem_util", "gpu_temp"])

            # Add disk I/O fields if available
            disk_info = monitor.get_disk_io_info()
            has_disk_io = "status" not in disk_info
            if has_disk_io:
                header.extend(
                    [
                        "disk_read_mb",
                        "disk_write_mb",
                        "disk_read_ops",
                        "disk_write_ops",
                        "primary_disk_usage_pct",
                    ]
                )

            with open(args.output, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)

                print(f"Recording metrics to {args.output}... Press Ctrl+C to stop.")

                try:
                    while True:
                        # Get current metrics
                        cpu_info = monitor.get_cpu_info()
                        memory_info = monitor.get_memory_info()
                        disk_info = monitor.get_disk_io_info()
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # Basic metrics
                        row = [
                            timestamp,
                            cpu_info["average_usage"],
                            memory_info["percent"],
                            memory_info["used"] / (1024**3),  # GB
                            memory_info["total"] / (1024**3),  # GB
                        ]

                        # Add GPU metrics if available
                        if has_gpu:
                            gpu_info = monitor.get_gpu_info()
                            row.extend(
                                [
                                    gpu_info.get("gpu_utilization", 0),
                                    gpu_info.get("memory_utilization", 0),
                                    gpu_info.get("temperature", 0),
                                ]
                            )

                        # Add disk I/O metrics if available
                        if has_disk_io:
                            total_io = disk_info["total"]
                            read_mb = total_io["read_bytes"] / (1024**2)
                            write_mb = total_io["write_bytes"] / (1024**2)

                            # Get primary disk usage percentage
                            primary_disk_usage = 0
                            if disk_info["usage"]:
                                primary_disk_usage = next(
                                    iter(disk_info["usage"].values())
                                )["percent"]

                            row.extend(
                                [
                                    read_mb,
                                    write_mb,
                                    total_io["read_count"],
                                    total_io["write_count"],
                                    primary_disk_usage,
                                ]
                            )

                        # Write to CSV
                        writer.writerow(row)
                        f.flush()  # Make sure data is written

                        # Status update
                        print(f"Recorded data point at {timestamp}", end="\r")

                        # Wait before next sample
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nRecording stopped by user.")
        elif args.graph:
            try:
                curses.wrapper(display_monitor_graph)
            except curses.error as e:
                print(f"Terminal error: {e}")
                print(
                    "Try resizing your terminal or use a different terminal emulator."
                )
            except Exception as e:
                logging.error(f"Unexpected error in graph mode: {e}")
                print(f"An error occurred: {e}")
        else:
            try:
                curses.wrapper(display_monitor)
            except curses.error as e:
                print(f"Terminal error: {e}")
                print(
                    "Try resizing your terminal or use a different terminal emulator."
                )
            except Exception as e:
                logging.error(f"Unexpected error in display mode: {e}")
                print(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print("Monitor stopped by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print(f"Error: {e}")
        print("Check hw_monitor.log for details.")


if __name__ == "__main__":
    main()

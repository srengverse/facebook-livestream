import psutil
import time

class SystemMonitor:
    def __init__(self):
        self.start_time = time.time()

    def get_system_stats(self):
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Network stats
        net_io = psutil.net_io_counters()
        
        return {
            'cpu_usage': cpu_usage,
            'memory_usage': memory.percent,
            'memory_available': memory.available / (1024 * 1024), # MB
            'disk_usage': disk.percent,
            'network_sent': net_io.bytes_sent,
            'network_recv': net_io.bytes_recv,
            'uptime': int(time.time() - self.start_time)
        }

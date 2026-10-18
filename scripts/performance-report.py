#!/usr/bin/env python3
"""Read-only CPU/temperature sample. Run during the workload that causes heat.

Prints process names and resource counters, never command lines or VPN profiles.
Does not generate traffic, launch workloads, or change network/power settings.
"""
import argparse
import json
import os
import time
from pathlib import Path


def processes():
    result = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            raw = path.read_text()
            fields = raw.rsplit(')', 1)[1].split()
            name = raw.split('(', 1)[1].rsplit(')', 1)[0]
            result[(int(path.parent.name), fields[19])] = (name, int(fields[11]) + int(fields[12]))
        except (OSError, ValueError, IndexError):
            continue
    return result


def temperatures():
    result = {}
    for chip in Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            name = (chip / 'name').read_text().strip()
        except OSError:
            continue
        for sensor in chip.glob('temp*_input'):
            try:
                value = int(sensor.read_text()) / 1000
                if 0 < value < 150:
                    result[name] = max(result.get(name, value), value)
            except (OSError, ValueError):
                continue
    return result


def service_cpu():
    try:
        lines = Path('/sys/fs/cgroup/system.slice/velum.service/cpu.stat').read_text().splitlines()
        return {key: int(value) for key, value in (line.split() for line in lines)}
    except (OSError, ValueError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=15, choices=range(5, 121), metavar='5..120')
    args = parser.parse_args()
    start_processes, start_service = processes(), service_cpu()
    started = time.monotonic()
    peaks = temperatures()
    for _ in range(args.seconds):
        time.sleep(1)
        for chip, value in temperatures().items():
            peaks[chip] = max(peaks.get(chip, value), value)
    elapsed = time.monotonic() - started
    cpu_hz = os.sysconf('SC_CLK_TCK')
    rows = []
    for identity, (name, ticks) in processes().items():
        if identity in start_processes:
            cpu = 100 * (ticks - start_processes[identity][1]) / cpu_hz / elapsed
            rows.append({'process': name, 'pid': identity[0], 'cpu_percent_one_core': round(cpu, 2)})
    finish_service = service_cpu()
    report = {'sample_seconds': round(elapsed, 1), 'logical_cpus': os.cpu_count(),
              'peak_temperature_celsius_by_sensor': peaks,
              'top_processes': sorted(rows, key=lambda row: row['cpu_percent_one_core'], reverse=True)[:10]}
    if 'usage_usec' in start_service and 'usage_usec' in finish_service:
        report['velum_service_cpu_percent_one_core'] = round(
            (finish_service['usage_usec'] - start_service['usage_usec']) / 10000 / elapsed, 2)
        report['velum_throttled_periods'] = finish_service.get('nr_throttled', 0) - start_service.get('nr_throttled', 0)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

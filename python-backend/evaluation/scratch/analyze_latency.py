import json

with open('evaluation/results/latest_results.json') as f:
    d = json.load(f)

cases = d['results']['sql_generation']
sorted_cases = sorted(cases, key=lambda x: x['latency_ms'], reverse=True)

print('All 30 tests sorted by latency (slowest first):')
print(f"{'Rank':<5} {'Test ID':<10} {'Latency (ms)':<16} Question")
print('-'*100)
for rank, tc in enumerate(sorted_cases, 1):
    ms = tc['latency_ms']
    print(f"{rank:<5} {tc['id']:<10} {ms:<16.1f} {tc['question'][:70]}")

print()
buckets = {'<5s': 0, '5-10s': 0, '10-20s': 0, '20-30s': 0, '30-45s': 0, '45-60s': 0, '>60s': 0}
slow_cases = []
for tc in cases:
    ms = tc['latency_ms']
    if ms < 5000: buckets['<5s'] += 1
    elif ms < 10000: buckets['5-10s'] += 1
    elif ms < 20000: buckets['10-20s'] += 1
    elif ms < 30000: buckets['20-30s'] += 1
    elif ms < 45000: buckets['30-45s'] += 1
    elif ms < 60000: buckets['45-60s'] += 1
    else: buckets['>60s'] += 1
    if ms > 20000:
        slow_cases.append(tc)

print('Latency Distribution:')
for k, v in buckets.items():
    print(f'  {k:<10}: {v}')

print()
print('Cases exceeding 20 seconds:')
for tc in sorted(slow_cases, key=lambda x: x['latency_ms'], reverse=True):
    print(f"  {tc['id']} - {tc['latency_ms']/1000:.2f}s - {tc['question'][:70]}")


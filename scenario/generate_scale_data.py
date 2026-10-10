import json
import random
import argparse
import csv

def generate_scale(num_rows):
    random.seed(12345)
    print(f"Generating synthetic scale data for {num_rows} rows...")
    
    # Generate large requests.csv
    requests = []
    urgencies = ['critical', 'high', 'medium', 'low']
    types = ['generator', 'boat', 'medical_supply', 'shelter_capacity', 'volunteer', 'vehicle']
    
    for i in range(num_rows):
        requests.append({
            "request_id": f"req-{i}",
            "resource_type_needed": random.choice(types),
            "quantity_requested": random.randint(1, 50),
            "urgency_level": random.choices(urgencies, weights=[10, 20, 50, 20])[0],
            "lat": 13.0 + random.uniform(-0.1, 0.1),
            "lon": 80.2 + random.uniform(-0.1, 0.1)
        })
        
    with open(f'scale_requests_{num_rows}.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=requests[0].keys())
        writer.writeheader()
        writer.writerows(requests)
        
    print(f"Generated scale_requests_{num_rows}.csv successfully.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=10000, help="Number of rows to generate (e.g. 10000, 100000, 1000000)")
    args = parser.parse_args()
    generate_scale(args.rows)

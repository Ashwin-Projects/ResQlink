import json
import random

def generate_events(steps=10):
    random.seed(999)
    print(f"Generating {steps} hazard expansion events...")
    
    events = []
    base_lat, base_lon = 12.97, 80.20
    
    for i in range(steps):
        # Hazard expands by 0.005 degrees per step
        expansion = i * 0.005
        poly = [[
            [base_lon - expansion, base_lat - expansion],
            [base_lon + 0.03 + expansion, base_lat - expansion],
            [base_lon + 0.03 + expansion, base_lat + 0.02 + expansion],
            [base_lon - expansion, base_lat + 0.02 + expansion],
            [base_lon - expansion, base_lat - expansion]
        ]]
        events.append({
            "event_id": i,
            "timestamp_offset_mins": i * 30,
            "hazard_type": "flood",
            "severity": "critical" if i > 5 else "high",
            "geometry": {
                "type": "Polygon",
                "coordinates": poly
            }
        })
        
    with open('hazard_events.json', 'w') as f:
        json.dump(events, f, indent=2)
        
    print("Generated hazard_events.json successfully.")

if __name__ == '__main__':
    generate_events()

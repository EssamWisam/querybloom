
import json
import argparse
import sys
import os
from tqdm import tqdm

from querybloom.executor.sparql_executor import execute_sparql_query

def process_file(input_file, output_file, endpoint="sockg-local"):
    """
    Reads a JSONL file, handles SPARQL queries, and writes the results to a new file.
    """
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        return

    print(f"Reading from {input_file}...")
    print(f"Using endpoint: {endpoint}")

    results = []
    with open(input_file, 'r') as f:
        lines = f.readlines()
        
    print(f"Processing {len(lines)} queries...")
    
    with open(output_file, 'w') as out_f:
        for line in tqdm(lines):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON line: {line[:50]}...")
                continue
                
            sparql_query = data.get('sparql')
            if sparql_query:
                try:
                    # Execute the SPARQL query
                    execution_result = execute_sparql_query(sparql_query, endpoint=endpoint)
                    data['execution_results'] = execution_result
                except Exception as e:
                    print(f"Error executing query for ID {data.get('id', 'unknown')}: {e}")
                    data['execution_results'] = {"success": False, "error_message": str(e)}
            else:
                data['execution_results'] = {"success": False, "error_message": "No SPARQL query found"}
            
            # Write line immediately to output file
            out_f.write(json.dumps(data) + "\n")
            out_f.flush()

    print(f"Finished processing. Output saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add SPARQL execution results to a JSONL file.")
    parser.add_argument("input_file", help="Path to the input JSONL file")
    parser.add_argument("--output_file", help="Path to the output JSONL file (optional)")
    parser.add_argument("--endpoint", default="sockg-local", help="SPARQL endpoint name (default: sockg-local)")

    args = parser.parse_args()

    input_path = args.input_file
    if args.output_file:
        output_path = args.output_file
    else:
        # Default output name: input_name_with_results.jsonl
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_with_results{ext}"

    process_file(input_path, output_path, args.endpoint)

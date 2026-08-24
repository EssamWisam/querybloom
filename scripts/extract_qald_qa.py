import json
import os

input_file = "ABSTAT/subgraphs_output/qa_output/qald9-test.jsonl"
output_file = "ABSTAT/subgraphs_output/qa_output/qald9-test-extracted.jsonl"

def extract_qa():
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    with open(input_file, 'r', encoding='utf-8') as fin, \
         open(output_file, 'w', encoding='utf-8') as fout:
        for line in fin:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Extract only question and sparql
                extracted = {
                    "question": data.get("question"),
                    "sparql": data.get("sparql")
                }
                fout.write(json.dumps(extracted, ensure_ascii=False) + '\n')
            except json.JSONDecodeError as e:
                print(f"Skipping invalid JSON line: {e}")

    print(f"Extraction complete. New file created at: {output_file}")

if __name__ == "__main__":
    extract_qa()

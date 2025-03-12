import json
import requests

# Define the backend URL
url = "http://localhost:8002/solve"
headers = {"Content-Type": "application/json"}

# Function to send a query to the backend and get the response
def get_response(query):
    data = {"inputs": query}
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=20)
    return response.json()

# Function to process a batch of queries
def process_batch(input_file, output_file):
    # Load queries from the input JSON file
    with open(input_file, "r", encoding="utf-8") as f:
        queries = json.load(f)

    # Prepare the output list
    results = []

    # Process each query
    for query in queries:
        print(f"Processing query: {query}")
        try:
            response = get_response(query)
            results.append({"query": query, "response": response})
        except Exception as e:
            print(f"Error processing query '{query}': {e}")
            results.append({"query": query, "response": None, "error": str(e)})

    # Save results to the output JSON file
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"Batch processing complete. Results saved to {output_file}")

# Example usage
if __name__ == "__main__":
    input_file = "queries.json"  # Input file containing queries
    output_file = "results.json"  # Output file to save results

    process_batch(input_file, output_file)

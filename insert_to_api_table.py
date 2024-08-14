import json
import asyncio
import asyncpg
from faker import Faker
import pandas as pd

fake = Faker()

async def insert_or_update_api_tests(conn, api_tests):
    for test in api_tests:
        await conn.execute('''
            INSERT INTO api_tests (url, request_method, payload, expected_response_code, expected_response_json, dependency_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (url, request_method)
            DO UPDATE SET payload = EXCLUDED.payload,
                          expected_response_code = EXCLUDED.expected_response_code,
                          expected_response_json = EXCLUDED.expected_response_json,
                          dependency_id = EXCLUDED.dependency_id
        ''', test['url'], test['request_method'], json.dumps(test['payload']), test['expected_response_code'], json.dumps(test['expected_response_json']), test['dependency_id'])

def resolve_ref(ref, components):
    ref_name = ref.split('/')[-1]
    return components.get(ref_name, {})

def generate_payload(schema, components):
    if '$ref' in schema:
        schema = resolve_ref(schema['$ref'], components)
    payload = {}
    for prop, details in schema.get('properties', {}).items():
        if details['type'] == 'string':
            payload[prop] = fake.word()
        elif details['type'] == 'integer':
            payload[prop] = fake.random_int()
        elif details['type'] == 'boolean':
            payload[prop] = fake.boolean()
        # Add more types as needed
    return payload

def extract_example_or_schema(schema, components):
    if '$ref' in schema:
        schema = resolve_ref(schema['$ref'], components)
    if 'example' in schema:
        return schema['example']
    elif 'properties' in schema:
        return {prop: f"<{details['type']}>" for prop, details in schema['properties'].items()}
    return schema

async def read_openapi_and_insert_to_db(openapi_file, db_config):
    # Read OpenAPI JSON file
    with open(openapi_file, 'r') as f:
        openapi_spec = json.load(f)

    components = openapi_spec.get('components', {}).get('schemas', {})
    
    # Extract API tests from OpenAPI spec
    api_tests = []
    for path, methods in openapi_spec.get('paths', {}).items():
        for method, details in methods.items():
            payload = None
            if 'requestBody' in details:
                content = details['requestBody'].get('content', {}).get('application/json', {})
                schema = content.get('schema', {})
                payload = generate_payload(schema, components)

            responses = details.get('responses', {})
            for code, response in responses.items():
                if int(code) >= 200 and int(code) < 300:  # Successful responses
                    content = response.get('content', {}).get('application/json', {})
                    schema = content.get('schema', {})
                    expected_response_json = extract_example_or_schema(schema, components)
                    
                    api_tests.append({
                        'url': f"http://127.0.0.1:8000{path}",
                        'request_method': method.upper(),
                        'payload': payload,
                        'expected_response_code': int(code),
                        'expected_response_json': expected_response_json,
                        'dependency_id': None  # Adjust based on your dependency logic
                    })

    # Connect to PostgreSQL database
    conn = await asyncpg.connect(**db_config)

    # Insert or update API tests into the database
    await insert_or_update_api_tests(conn, api_tests)

    await conn.close()

async def fetch_db_table(db_config):
    conn = await asyncpg.connect(**db_config)
    rows = await conn.fetch('SELECT * FROM api_tests')
    await conn.close()
    df_db = pd.DataFrame(rows, columns=['id', 'url', 'request_method', 'payload', 'expected_response_code', 'expected_response_json', 'dependency_id'])
    return df_db

if __name__ == "__main__":
    db_config = {
        'user': 'postgres',
        'password': '123456',
        'database': 'postgres',
        'host': '127.0.0.1'
    }
    openapi_file = 'openapi.json'

    # Read OpenAPI JSON and insert or update the database
    asyncio.run(read_openapi_and_insert_to_db(openapi_file, db_config))

    # Fetch and display the current state of the table in the database
    df_db_current = asyncio.run(fetch_db_table(db_config))
    print("Current State of API Tests Table:")
    print(df_db_current)

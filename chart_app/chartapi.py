import frappe
import pandas as pd
import os
import re
import openai
from typing import List, Dict, Any, Optional
from datetime import datetime


# Initialize OpenAI API Key
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "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"))

openai.api_key = os.getenv("OPENAI_API_KEY", "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")



def read_frappe_table(table_name: str):
    try:
        # SQL query to fetch all data from the specified table
        query = f"SELECT * FROM `tab{table_name}`"
        
        # Execute the SQL query
        data = frappe.db.sql(query, as_dict=True)
        
        if not data:
            raise ValueError(f"No data found in table {table_name}")

        # Log the raw data for debugging purposes
        # frappe.log("Fetched data from the table: {}".format(data))
        
        # Preprocess data to handle datetime and None values
        for record in data:
            for key, value in record.items():
                # Check if value is of datetime type
                if isinstance(value, datetime):
                    record[key] = value.isoformat()  # Convert to ISO format string
                elif value is None:
                    record[key] = None  # Ensure None values are maintained

        return data, table_name  # Return the raw data and table name
    except Exception as e:
        frappe.log_error(f"Failed to fetch data from table {table_name}. Error: {str(e)}")
        frappe.throw(f"Failed to fetch data from table {table_name}. Error: {str(e)}")


# Generate a table schema string from a DataFrame
def get_table_schema(df,table_name):
    # Prepare the table name (tables in Frappe are prefixed with 'tab')
    table_name = f"tab{table_name}"
    
    # Execute SQL query to get the table schema
    schema = frappe.db.sql(f"DESCRIBE `{table_name}`", as_dict=True)
    
    # Start building the table schema string
    table_schema = f'"""\nTable: {table_name}\nColumns:'
    
    for column in schema:
        # Formatting the column type (converting MySQL types to general SQL types)
        column_type = column['Type'].upper()
        
        if 'varchar' in column_type:
            column_type = 'VARCHAR'
        elif 'int' in column_type:
            column_type = 'INT'
        elif 'float' in column_type:
            column_type = 'FLOAT'
        elif 'date' in column_type:
            column_type = 'DATE'
        elif 'text' in column_type:
            column_type = 'TEXT'
        
        # Append the column information in the required format
        table_schema += f'\n- {column["Field"]} ({column_type})'
    
    # End of schema string
    table_schema += '\n"""'
    
    # Return or print the table schema
    return table_schema

# Function to refine the SQL query
def refine_sql_query(sql_query: str) -> str:
    sql_lower = sql_query.lower()
    select_start = sql_lower.find('select')
    if select_start == -1:
        return sql_query

    query_end = sql_lower.find(';', select_start)
    if query_end == -1:
        query_end = len(sql_lower)
    else:
        query_end += 1

    refined_query = sql_query[select_start:query_end]
    refined_query = ' '.join(refined_query.split())

    keywords = ['SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN',
                'INNER JOIN', 'OUTER JOIN', 'ON', 'AND', 'OR', 'AS']
    for keyword in keywords:
        refined_query = re.sub(r'\b' + keyword.lower() + r'\b', keyword, refined_query, flags=re.IGNORECASE)

    return refined_query

# Generate SQL query using OpenAI based on user query and table schema

def get_sql_query(user_query: str, table_schema: str, model: str, system_prompt: str, user_prompt_template: str) -> str:
    user_prompt = user_prompt_template.format(table_schema=table_schema, user_query=user_query)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages
        )
        sql_query = response.choices[0].message.content.strip()
        if not sql_query:
            raise ValueError("Generated SQL query is empty or None.")
        return sql_query
    except Exception as e:
        raise ValueError(f"An error occurred while generating SQL query: {str(e)}")

    # except Exception as e:
    #     frappe.log_error(f"Error during SQL generation: {str(e)}")
    #     frappe.throw(f"Error during SQL generation: {str(e)}")

# Analyze the SQL query and suggest a chart type
def analyze_sql_query(sql_query: str) -> Dict[str, Any]:
    sql_final = refine_sql_query(sql_query)
    # frappe.log("Fetched data from the table: {}".format(sql_query))
    aggregations = re.findall(r'(sum|avg|count|max|min)\s*\(', sql_final, re.IGNORECASE)
    group_by_match = re.search(r'\bgroup\s+by\s+(.+?)(?:\border\s+by|\blimit\b|;\s*$|\\\s*$|$)', sql_final, re.IGNORECASE | re.DOTALL)
    order_by = re.search(r'\border\s+by\b', sql_final, re.IGNORECASE) is not None
    limit = re.search(r'\blimit\b', sql_final, re.IGNORECASE) is not None
    time_columns = re.findall(r'\b(date|time|year|month|day)\b', sql_final)
    select_clause = re.search(r'select\s+(.+?)\s+from', sql_final, re.DOTALL | re.IGNORECASE)
    
    if not select_clause:
        return {'chart_type': 'table', 'x_axis': '', 'y_axis': ''}

    columns = re.findall(r'(["\w\s/]+?)(?:,|\s+as\s+|\s+from\s+)', select_clause.group(1), re.IGNORECASE)
    columns = [col.strip().strip('"') for col in columns]

    if aggregations and group_by_match:
        grouped_column = group_by_match.group(1).strip().strip('"')
        aggregated_column = next((col for col in columns if any(agg in col.lower() for agg in aggregations)), '')

        if order_by and limit:
            chart_type = 'bar'
        elif time_columns:
            chart_type = 'line' if len(aggregations) == 1 else 'multi-series line'
        else:
            chart_type = 'bar' if len(aggregations) == 1 else 'multi-series bar'

        # frappe.log("Fetched data from the table grouped_column: {}".format(grouped_column))
        x_axis = grouped_column
        y_axis = aggregated_column
    elif aggregations and not group_by_match:
        chart_type = 'bar'
        x_axis = columns[0]
        y_axis = next((col for col in columns if any(agg in col.lower() for agg in aggregations)), columns[-1])
    elif not aggregations and not group_by_match:
        chart_type = 'scatter'
        x_axis = columns[0]
        y_axis = ', '.join(columns[1:]) if len(columns) > 1 else ''
    else:
        chart_type = 'table'
        x_axis = columns[0]
        y_axis = ', '.join(columns[1:]) if len(columns) > 1 else ''

    if not y_axis:
        as_clause = re.search(r'\bas\s+(\w+)', sql_final, re.IGNORECASE)
        if as_clause:
            y_axis = as_clause.group(1)

    return {
        "sql_query": sql_final,
        'chart_type': chart_type,
        'x_axis': x_axis,
        'y_axis': y_axis
    }

# Main function to process the Frappe table and generate SQL query
@frappe.whitelist(allow_guest=True)
def main_parse_frappe(user_query: str, is_new_data_source: bool,table_name:str, model: str = "gpt-3.5-turbo", system_prompt: Optional[str] = None,
                      user_prompt_template: Optional[str] = None) -> Dict[str, Any]:
    try:
        # Read Frappe table instead of file
        table_name = table_name
        df, table_name = read_frappe_table(table_name)
        
        table_schema = get_table_schema(df, table_name)
        

        # Set default prompts if not provided
        if system_prompt is None:
            system_prompt = "You are an expert SQL query generator. Your task is to convert natural language queries into accurate and efficient SQL queries based on the provided table schema."

        if user_prompt_template is None:
            user_prompt_template = """
                                    Given the following table schema:
                                    {table_schema}
                                    Generate a SQL query for the following user request:
                                    {user_query}
                                    Provide only the SQL query without any additional explanation.
                                    """

        # # Generate SQL query
        sql_query = get_sql_query(user_query, table_schema, model, system_prompt, user_prompt_template)
        # return sql_query,table_schema
        if sql_query:
            query_chart_suggestion = analyze_sql_query(sql_query)
            # return {
            #     "status": "success",
            #     "sql_query": sql_query,
            #     "table_schema": table_schema,
            #     "model_used": model,
            #     "chart_suggestion": query_chart_suggestion
            # }
            return fetch_data_for_chart(query_chart_suggestion)
        else:
            return {
                "status": "error",
                "message": "Failed to generate SQL query"
            }
    except Exception as e:
        # frappe.log_error(f"An error occurred: {str(e)}")
        return {
            "status": "error",
            "message": f"An error occurred: {str(e)}"
        }


def fetch_data_for_chart(query_chart_suggestion):
    try:
        # Execute the provided SQL query
        data = frappe.db.sql(query_chart_suggestion.get("sql_query"), as_dict=True)
        # frappe.log("Fetched chart dataset: {}".format(data))
        # frappe.log("Fetched chart dataset: {}".format(query_chart_suggestion))
        
        if not data:
            raise ValueError("No data found for the executed SQL query.")
        
        # Prepare the dataset for the chart
        dataset = {
            "chart_type": query_chart_suggestion.get("chart_type"),
            "data": []
        }
        
        # Determine the x_axis and y_axis
        x_axis_keys = [key.strip() for key in query_chart_suggestion.get("x_axis").split(',')]
        y_axis_keys = [key.strip() for key in query_chart_suggestion.get("y_axis").split(',')]
        
        # Populate the data based on x_axis and y_axis
        for record in data:
            data_entry = {}
            for x_key in x_axis_keys:
                # Concatenate x_axis values if there are multiple
                if x_key in record:
                    data_entry[x_key] = record[x_key]
            
            # Add y_axis values to the data entry
            for y_key in y_axis_keys:
                if y_key in record:
                    data_entry[y_key] = record[y_key]
            
            # Append the constructed data entry to the dataset
            dataset["data"].append(data_entry)

        # Log the fetched dataset for debugging purposes
        # frappe.log("Fetched chart dataset: {}".format(dataset))

        return dataset
    except Exception as e:
        # frappe.log_error(f"Failed to fetch data for chart. Error: {str(e)}")
        frappe.throw(f"Failed to fetch data for chart. Error: {str(e)}")

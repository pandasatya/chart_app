import frappe
import json
import requests
from frappe.utils import random_string

# Define reserved keywords
RESERVED_KEYWORDS = [
    "meta", "doctype", "name", "parent", "owner", "modified", "idx", "creation", 
    "modified_by", "parentfield", "parenttype", "docstatus", "naming_series"
]

@frappe.whitelist(allow_guest=True)
def upload_and_process_json():
    # Fetch JSON data from the provided URL
    url = "https://dummyjson.com/products"
    response = requests.get(url)

    if response.status_code != 200:
        frappe.throw("Failed to fetch data from the provided URL")

    # Load JSON data with exception handling
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        frappe.throw(f"JSON decode error: {str(e)}")
    
    if not data or 'products' not in data:
        frappe.throw("No product data found in the JSON response")

    # Extract the product list
    products = data['products']

    # Dynamically extract keys and assign field types based on the first record
    columns, child_tables = determine_columns(products)

    # Dynamically create a DocType and insert data
    doctype_name = create_dynamic_doctype(columns, child_tables)
    insert_data_into_doctype(doctype_name, products, child_tables)

    # Prepare and return data for chart generation
    chart_data = prepare_chart_data(products)

    return {
        "status": "success",
        "doctype": doctype_name,
        "chart_data": chart_data  # Return chart data
    }

def sanitize_fieldname(fieldname):
    """
    Sanitize the fieldname to avoid conflicts with reserved keywords or invalid names.
    """
    sanitized = fieldname.lower().replace(" ", "_")
    
    if sanitized in RESERVED_KEYWORDS:
        sanitized = f"{sanitized}_field"  # Append '_field' to avoid conflict

    return sanitized

def determine_columns(data):
    """
    Determine the columns and their appropriate field types based on the first data entry.
    """
    columns = {}
    child_tables = {}
    first_row = data[0] if data else {}

    for key, value in first_row.items():
        fieldname = sanitize_fieldname(key)

        # Determine the field type dynamically
        if isinstance(value, list):
            # For lists, create a child table
            child_table_name = f"{fieldname}_child"
            child_tables[fieldname] = child_table_name
            columns[fieldname] = "Table"  # Field type as Table
        elif isinstance(value, bool):
            columns[fieldname] = "Check"  # Store booleans as Check (checkbox)
        elif isinstance(value, int):
            columns[fieldname] = "Int"  # Store integers as Int
        elif isinstance(value, float):
            columns[fieldname] = "Float"  # Store floats as Float
        else:
            columns[fieldname] = "Data"  # Default to Data for strings or other values

    return columns, child_tables

def create_dynamic_doctype(columns, child_tables):
    """
    Create a new DocType based on the keys of the JSON data.
    """
    # Ensure unique DocType name by appending a random string
    doctype_name = f"Product_Data_{random_string(5)}"

    if not frappe.db.exists("DocType", doctype_name):
        try:
            # Create child tables
            for child_table_name in child_tables.values():
                create_child_table(child_table_name)

            # Define the fields dynamically from the keys of the JSON
            fields = []
            for fieldname, fieldtype in columns.items():
                field = {
                    "fieldname": fieldname, 
                    "fieldtype": fieldtype, 
                    "label": fieldname.replace("_", " ").title()
                }

                # If the field is a Table, set the child table options
                if fieldtype == "Table":
                    field["options"] = child_tables[fieldname]  # Link to child DocType

                # Set Data field length to 250 characters
                if fieldtype == "Data":
                    field["length"] = 250  # Set max length for Data fields

                # Set Text fields to Long Text for larger values
                if fieldtype == "Text":
                    field["fieldtype"] = "Long Text"  # Use Long Text for larger text fields

                fields.append(field)

            # Create the DocType dynamically
            doc = frappe.get_doc({
                "doctype": "DocType",
                "name": doctype_name,
                "module": "Custom",
                "custom": 1,
                "fields": fields,
                "autoname": "autoincrement",
                "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]
            })
            doc.insert()

        except frappe.exceptions.DuplicateEntryError as e:
            frappe.log_error(f"Duplicate DocType error: {str(e)}")
            return doctype_name  # Return existing name or handle as needed

    return doctype_name

def create_child_table(child_table_name):
    """
    Create a child table for storing list data.
    """
    try:
        # Create child DocType with a Data field set to 250 character length
        child_fields = [{
            "fieldname": "value",
            "fieldtype": "Data",
            "label": "Value",
            "length": 250  # Set max length for Data field
        }]
        
        child_doc = frappe.get_doc({
            "doctype": "DocType",
            "name": child_table_name,
            "module": "Custom",
            "istable": 1,  # This makes it a child table
            "custom": 1,
            "fields": child_fields,
            "autoname": "autoincrement",
            "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]
        })
        child_doc.insert()
        return child_doc.name

    except frappe.exceptions.DuplicateEntryError as e:
        frappe.log_error(f"Duplicate child table error: {str(e)}")
        return child_table_name  # Return existing name or handle as needed

def insert_data_into_doctype(doctype_name, data, child_tables):
    """
    Insert data into the specified DocType dynamically.
    """
    for row in data:
        # Create a new document for each row
        doc = frappe.get_doc({"doctype": doctype_name})

        # Map the values from the JSON to the fields in the DocType
        for field, value in row.items():
            field_name = sanitize_fieldname(field)

            if isinstance(value, list):
                # Handle list values for child tables
                if field_name in child_tables:
                    child_table_name = child_tables[field_name]
                    child_entries = []
                    for item in value:
                        if isinstance(item, dict):
                            # Ensure item in list is not a dict or handle accordingly
                            item = frappe.utils.json.dumps(item)  # Convert dict to JSON string
                        child_entries.append({
                            "doctype": child_table_name,
                            "parentfield": field_name,  # Link field for child table
                            "value": item  # Store list item as 'value'
                        })
                    doc.set(field_name, child_entries)
            elif isinstance(value, dict):
                # Flatten the dictionary or convert it to a JSON string
                json_value = frappe.utils.json.dumps(value)  # Convert to JSON string
                doc.set(field_name, json_value)  # Set the JSON string as the field value
            else:
                # Set the simple value directly
                doc.set(field_name, value)

        # Insert the new document
        try:
            doc.insert()
        except Exception as e:
            frappe.throw(f"Error inserting document: {str(e)}")

def prepare_chart_data(products):
    """
    Prepare the data for bar chart generation.
    """
    # Example: Prepare bar chart data for product prices vs. titles
    labels = [product['title'] for product in products]  # Product titles as labels
    data_points = [product['price'] for product in products]  # Product prices as data points

    chart_data = {
        "labels": labels,
        "datasets": [{
            "label": "Product Prices",
            "data": data_points
        }]
    }

    return chart_data

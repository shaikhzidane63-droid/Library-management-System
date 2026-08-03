import mysql.connector

try:
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Zndag8",  # Put your MySQL password here if you have one
        database="library_management_system"
    )

    print("Connected to MySQL successfully!")

except Exception as e:
    print("Error:", e)
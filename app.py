from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
import boto3
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')  # Using secret key from the .env file

# AWS RDS MySQL Configuration (use your actual credentials from the .env file)
RDS_HOST = os.getenv('RDS_HOST')
RDSPORT = int(os.getenv('RDSPORT'))
RDS_USER = os.getenv('RDS_USER')
RDS_PASSWORD = os.getenv('RDS_PASSWORD')
RDS_DB_NAME = os.getenv('RDS_DB_NAME')

# AWS S3 Configuration (use your actual S3 bucket from the .env file)
S3_BUCKET = os.getenv('S3_BUCKET')
S3_REGION = os.getenv('S3_REGION')

# Initialize boto3 clients for S3
s3 = boto3.client('s3', region_name=S3_REGION)

# MySQL connection
rds_conn = mysql.connector.connect(
    host=RDS_HOST,
    port=RDSPORT,
    user=RDS_USER,
    password=RDS_PASSWORD,
    database=RDS_DB_NAME
)

# Table creation (Run this once in your DB setup or ensure table exists)
def create_user_table():
    cursor = rds_conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(50) NOT NULL 
    );
    """)
    rds_conn.commit()
    cursor.close()

create_user_table()

# Route for index
@app.route('/')
def index():
    return redirect(url_for('login'))

# Registration Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']  # Accept role input (student or instructor)
        hashed_password = generate_password_hash(password)

        # Insert user into MySQL RDS
        try:
            cursor = rds_conn.cursor()
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", (username, hashed_password, role))
            rds_conn.commit()
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            rds_conn.rollback()
            flash('Username already exists. Try a different one.', 'danger')
        finally:
            cursor.close()

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        cursor = rds_conn.cursor()
        cursor.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user[0], password):
            session['username'] = username
            session['role'] = user[1]  # Store role in session
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')

        cursor.close()
    return render_template('login.html')


# Dashboard Route
@app.route('/dashboard')
def dashboard():
    if 'username' in session:
        username = session['username']
        return render_template('dashboard.html', username=username)
    return redirect(url_for('login'))

# Courses Route (Fetch from S3)
@app.route('/courses')
def courses():
    if 'username' not in session:
        return redirect(url_for('login'))

    # List course materials from the S3 bucket
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET)
        courses = []
        if 'Contents' in response:
            for item in response['Contents']:
                file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{item['Key']}"
                courses.append({"name": item['Key'], "url": file_url})

        # Pass role and courses to the template
        return render_template('courses.html', courses=courses, role=session.get('role'))

    except Exception as e:
        flash(f"Error retrieving course materials: {e}", 'danger')
        return redirect(url_for('dashboard'))


# Admin Route for Uploading Course Materials (only for instructors)
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'username' not in session:
        return redirect(url_for('login'))

    # Check if the user is an instructor
    cursor = rds_conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = %s", (session['username'],))
    role = cursor.fetchone()

    if role is None or role[0] != 'instructor':
        flash('You do not have permission to upload files.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # File Upload to S3
        file = request.files.get('course_file')
        if file:
            file_key = file.filename
            try:
                s3.upload_fileobj(file, S3_BUCKET, file_key)
                flash('File uploaded successfully.', 'success')
            except Exception as e:
                flash(f"File upload failed: {e}", 'danger')
        else:
            flash('No file selected.', 'danger')

    return render_template('admin.html')

# Route to delete a course file (only for instructors)
@app.route('/delete_file/<file_name>', methods=['POST'])
def delete_file(file_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Check if the user is an instructor
    cursor = rds_conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = %s", (session['username'],))
    role = cursor.fetchone()

    if role is None or role[0] != 'instructor':
        flash('You do not have permission to delete files.', 'danger')
        return redirect(url_for('courses'))

    try:
        # Deleting the file from S3 bucket
        s3.delete_object(Bucket=S3_BUCKET, Key=file_name)
        flash('File deleted successfully.', 'success')
    except Exception as e:
        flash(f"File deletion failed: {e}", 'danger')

    return redirect(url_for('courses'))


# Route for downloading a file
@app.route('/download_file/<file_name>', methods=['GET'])
def download_file(file_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    try:
        # Generate the file's URL for download from S3
        file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{file_name}"
        return redirect(file_url)
    except Exception as e:
        flash(f"File download failed: {e}", 'danger')
        return redirect(url_for('courses'))


# Logout Route
@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    return redirect(url_for('login'))


# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)

# Requirements Document

## HR & Payroll Department – Proposed Features

| Module | Features |
|---|---|
| Employee Management | Add Employee, Employee ID, Name, Mobile, Email, Department, Designation, Joining Date, Active/Inactive Status, Edit, Delete, Search & Filter |
| Attendance Management | Daily Attendance, Month-wise Attendance, Employee-wise Attendance, In Time, Out Time, Working Hours, Present Days, Present/Absent/Half Day, Late Hours, OT Hours, Attendance Edit/Correction, Attendance History, Excel Import |
| Salary / Payroll | Month-wise Salary, Employee-wise Salary, Basic Salary, Working Days, Per Day Salary, Present Days, Present Hours, Late Hours, OT Hours, Payment, Advance, Net Salary, Salary Status, Edit/Update, Salary History |
| Reports | Daily Attendance Report, Monthly Attendance Report, Employee-wise Attendance Report, Overtime Report, Monthly Salary Report, Employee-wise Salary History, Payroll Summary, Excel/PDF Export |
| Dashboard | Total Employees, Present, Absent, Late Employees, Total OT Hours, Attendance Summary, Total Salary, Total Advance, Paid Salary, Pending Salary |
| Access & Security | Role-based Access, HR/Admin Permissions, Payroll Data Restriction, Activity/Audit History |

---

## Requirements – Packaging List

### 1. Number of Rows / Boxes

- When creating a new **Packaging List**, add a separate **Number of Boxes** field next to the existing **Add Box** option.
- Based on the number entered, the system should automatically create the same number of rows below for entering the weight details.

### 2. Automatic Cursor Movement

- When a weight is entered in one row and the user presses **Enter**, the cursor should automatically move to the next row.
- This should reduce the need to manually click each row.

### 3. Prevent Data Loss on Window Close

- If the Packaging List window is accidentally closed before saving, the entered data should not be lost.
- When the user opens the Packaging List again, the previously entered data should be restored exactly as it was.
- The temporary data should be cleared **only after** the Packaging List is successfully saved.

### 4. PDF Table Optimization

- The Packaging List PDF should display **at least 40 rows on one page**.
- Reduce the row height/spacing in the PDF table so that more rows fit on a single page.
- The objective is to reduce the total number of PDF pages while keeping the table readable and properly formatted.

---

## Requirements – Quotation

### 1. Quotation Template for Kalika Infotech

- Create a quotation template for **Kalika Infotech** based on the existing quotation format.
- The template should follow the same layout, structure, and styling as the current quotation.

### 2. Company Selection

- When creating a quotation, provide an option to **select the company** (e.g., Kalika Enterprises, Kalika Infotech).
- Based on the selected company, the system should automatically use that company's:
  - Name
  - Address
  - Contact details
  - Logo
  - Other relevant information
- The selected company's details should be used while generating the quotation PDF.

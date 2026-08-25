# iCount Inventory Management System - User Manual

## Table of Contents
1. [Introduction](#introduction)
2. [User Roles and Permissions](#user-roles-and-permissions)
3. [Getting Started](#getting-started)
4. [Dashboard Overview](#dashboard-overview)
5. [Product Management](#product-management)
6. [Requisition Management](#requisition-management)
7. [User Administration](#user-administration)
8. [Company Management](#company-management)
9. [Activity Logs](#activity-logs)
10. [Stock Audits](#stock-audits)
11. [Pending Removals](#pending-removals)
12. [Scanner Functions](#scanner-functions)
13. [Reports and Analytics](#reports-and-analytics)
14. [Role-Specific Workflows and Scenarios](#role-specific-workflows-and-scenarios)
15. [Troubleshooting](#troubleshooting)

## Introduction

The iCount Inventory Management System is a comprehensive solution designed to help organizations efficiently manage their inventory, track stock levels, process requisitions, and maintain accurate records. This system provides role-based access control to ensure that users can only access features appropriate to their responsibilities.

### Key Features
- Real-time inventory tracking
- Barcode scanning capabilities
- Requisition processing workflow
- Stock level alerts and reorder notifications
- Expiry date tracking
- Audit trails and reporting
- Multi-company support
- Mobile-responsive design

## User Roles and Permissions

The system supports six distinct user roles, each with specific permissions and capabilities:

### 1. SYS-Admin (System Administrator)
**Description**: The highest privilege level with unrestricted access to all system features and data across all companies.

**Capabilities**:
- Full access to all companies, users, and system-wide settings
- Can view, create, edit, and delete all data
- Can manage company configurations
- Can assign roles to users
- Can perform system maintenance tasks
- Access to all reports and analytics

**Dashboard Access**:
- Complete inventory overview
- All requisitions across companies
- System-wide activity logs
- Performance metrics for all companies

**Detailed Permissions**:
- View all products across all companies
- Add/Edit/Delete products in any company
- Add/Remove stock for any product
- View and manage all requisitions
- Approve/Reject requisitions from any company
- View and manage all users
- Create/Edit/Delete users in any company
- View and manage all companies
- Create/Edit/Delete companies
- Access all activity logs
- Perform stock audits for any company
- Manage pending removals for any company
- Access mobile scanner on any device
- Generate all reports

### 2. WH-Admin (Warehouse Administrator)
**Description**: Company-specific administrative role with broad permissions within their assigned company.

**Capabilities**:
- Manage products within their company
- Process and approve requisitions
- Perform stock audits
- Manage pending removals
- Generate reports for their company
- Cannot delete users or companies

**Dashboard Access**:
- Company-specific inventory overview
- Requisitions from their company
- Activity logs for their company
- Stock movement analytics

**Detailed Permissions**:
- View all products within their assigned company
- Add/Edit/Delete products in their company only
- Add/Remove stock for products in their company
- View and manage requisitions from their company
- Approve/Reject requisitions from their company
- View users in their company
- Create/Edit users in their company
- Cannot manage companies
- View activity logs for their company
- Perform stock audits for their company
- Manage pending removals for their company
- Access mobile scanner on mobile devices
- Generate reports for their company

### 3. Company-Admin (Company Administrator)
**Description**: Company-specific administrative role focused on user management and reporting within their assigned company.

**Capabilities**:
- Manage users within their company
- View reports and activity logs
- Update their own profile information
- View product information and stock levels
- Cannot modify inventory quantities

**Dashboard Access**:
- Company inventory summary
- User activity within their company
- Low stock alerts
- Expiry notifications

**Detailed Permissions**:
- View all products within their assigned company
- Cannot Add/Edit/Delete products
- Cannot Add/Remove stock
- View requisitions from their company
- Cannot Approve/Reject requisitions
- View and manage users in their company
- Create/Edit users in their company
- Cannot manage companies
- View activity logs for their company
- Cannot perform stock audits
- Cannot manage pending removals
- Cannot access mobile scanner
- Generate reports for their company

### 4. Purchaser
**Description**: Company-specific role focused on monitoring inventory levels and generating procurement reports.

**Capabilities**:
- View products and inventory levels
- Generate and receive reports
- Monitor low stock alerts
- Cannot make changes to inventory
- Cannot process requisitions

**Dashboard Access**:
- Inventory status overview
- Low stock notifications
- Expiry alerts
- Favorite products list

**Detailed Permissions**:
- View all products within their assigned company
- Cannot Add/Edit/Delete products
- Cannot Add/Remove stock
- Cannot view requisitions
- Cannot manage users
- Cannot manage companies
- Cannot view activity logs
- Cannot perform stock audits
- Cannot manage pending removals
- Cannot access mobile scanner
- Generate and receive reports for their company

### 5. User (Regular User)
**Description**: Company-specific role with limited access focused on requisition submission.

**Capabilities**:
- Submit requisitions only
- View their own requisition history
- Cannot access administrative functions
- Cannot view inventory details beyond what's needed for requisitions

**Dashboard Access**:
- Redirected to requisition form upon login
- Personal requisition history
- Pending requisition status

**Detailed Permissions**:
- Cannot view products directly
- Cannot Add/Edit/Delete products
- Cannot Add/Remove stock
- Submit requisitions only
- View their own requisition history
- Cannot manage users
- Cannot manage companies
- Cannot view activity logs
- Cannot perform stock audits
- Cannot manage pending removals
- Cannot access mobile scanner
- Cannot generate reports

### 6. Unverified User
**Description**: Temporary role assigned to new users until email verification is completed.

**Capabilities**:
- Cannot log in until email is verified
- Limited to account verification process

## Getting Started

### Account Registration
1. Navigate to the system login page
2. Click on "Sign Up" to create a new account
3. Fill in your personal details including:
   - Full name
   - Username
   - Email address
   - Password
4. Submit the registration form
5. Check your email for a verification link
6. Click the verification link to activate your account

### Login Process
1. Enter your username and password
2. Click "Login"
3. You will be redirected based on your role:
   - Regular Users: Requisition form
   - Admin Roles: Dashboard

### Password Recovery
1. Click "Forgot Password" on the login page
2. Enter your email address
3. Check your email for a password reset link
4. Click the link and set a new password

## Dashboard Overview

The dashboard provides a centralized view of key inventory metrics and system activities. The content varies based on user role.

### Common Dashboard Elements
- **Welcome Section**: Personalized greeting with current date and time
- **Quick Actions**: Role-specific action buttons
- **Inventory Summary Cards**: Key metrics at a glance
- **Recent Activity**: Timeline of recent system events

### SYS-Admin Dashboard
- Total products across all companies
- Pending requisitions from all companies
- Low stock alerts across all companies
- Out of stock items
- Expiring products (30 days and 3 months)
- Recent activity logs from all companies

### WH-Admin Dashboard
- Total products in their company
- Pending requisitions from their company
- Low stock alerts for their company
- Out of stock items in their company
- Expiring products in their company
- Recent activity logs for their company

### Company-Admin Dashboard
- Inventory summary for their company
- User activity reports
- Low stock notifications
- Expiry alerts

### Purchaser Dashboard
- Inventory status overview
- Low stock notifications
- Expiry alerts
- Favorite products list

### User Dashboard
- Redirects to requisition form
- Personal requisition history
- Pending requisition status

## Product Management

### Viewing Products
**Available to**: All authenticated users except Unverified Users

**Features**:
- Search by product name, account title, or barcode
- Filter by account type, status (OK, Low Stock, No Stock, etc.)
- Sort by name, quantity, or other criteria
- Pagination for large product lists

**Role-Specific Access**:
- SYS-Admin: Can view products from all companies
- WH-Admin, Company-Admin, Purchaser: Can only view products from their company

### Adding Products
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Products" > "Add Product"
2. Fill in product details:
   - Product name
   - Account title
   - Unit of measure (UOM)
   - Initial quantity
   - Reorder level
   - Low stock threshold
3. System automatically generates a unique barcode
4. Click "Save" to add the product

**Role-Specific Restrictions**:
- Products are automatically assigned to the user's company
- SYS-Admin can optionally assign products to specific companies

### Editing Products
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to edit
3. Click the "Edit" button in the actions column
4. Modify the required fields
5. Click "Save" to update the product

**Role-Specific Restrictions**:
- Users can only edit products in their company
- SYS-Admin can edit any product from any company

### Deleting Products
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to delete
3. Click the "Delete" button in the actions column
4. Confirm the deletion in the popup dialog

**Role-Specific Restrictions**:
- Users can only delete products in their company
- SYS-Admin can delete any product from any company
- Deletion removes all associated batches, history, and requisition items

### Managing Stock Levels

#### Adding Stock
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to add stock to
3. Click the "Add Stock" button in the actions column
4. Enter the quantity to add
5. Provide supplier information (optional)
6. Click "Add Stock" to update inventory

#### Removing Stock
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to remove stock from
3. Click the "Remove Stock" button in the actions column
4. Enter the quantity to remove
5. Provide reason for removal (optional)
6. Click "Remove Stock" to update inventory

### Favorite Products
**Available to**: All authenticated users except Unverified Users

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to mark as favorite
3. Click the star icon next to the product name
4. The product will appear in your "Favorites" section on the dashboard

### Product History
**Available to**: All authenticated users except Unverified Users

**Process**:
1. Navigate to "Products" > "View Products"
2. Find the product you want to view history for
3. Click the "History" button in the actions column
4. View all transactions (additions and removals) for this product

## Requisition Management

### Creating Requisitions
**Available to**: User, SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Requisitions" > "New Requisition"
2. Search for products by name
3. Add items to your requisition:
   - Select product from search results
   - Enter quantity needed
   - Select appropriate unit of measure
4. Review your requisition
5. Click "Submit Requisition" to send for approval

**Role-Specific Behavior**:
- Regular Users: Requisitions are submitted for approval
- Admin Roles: Can approve their own requisitions (not recommended)

### Viewing Requisitions
**Available to**: All authenticated users

**Features**:
- Filter by status (Pending, Approved, Rejected)
- Search by requisition ID or product name
- Sort by date or status
- Pagination for large lists

**Role-Specific Access**:
- User: Only their own requisitions
- Company-Admin: Requisitions from their company
- WH-Admin: Requisitions from their company
- SYS-Admin: All requisitions across all companies

### Approving Requisitions
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Requisitions" > "View Requisitions"
2. Find the requisition to approve
3. Click the "Approve" button
4. Confirm stock availability
5. Click "Confirm Approval" to process

**System Actions**:
- Deducts requested quantities from inventory
- Updates requisition status to "Approved"
- Sends notification to requester
- Logs the approval activity

### Rejecting Requisitions
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Requisitions" > "View Requisitions"
2. Find the requisition to reject
3. Click the "Reject" button
4. Provide reason for rejection
5. Click "Confirm Rejection" to process

**System Actions**:
- Does not modify inventory
- Updates requisition status to "Rejected"
- Sends notification to requester with reason
- Logs the rejection activity

### Printing Delivery Forms
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Requisitions" > "View Requisitions"
2. Find an approved requisition
3. Click the "Print" button in the actions column
4. A printable delivery form will be generated

### Deleting Requisitions
**Available to**: SYS-Admin

**Process**:
1. Navigate to "Requisitions" > "View Requisitions"
2. Find the requisition to delete (must be approved or rejected)
3. Click the "Delete" button in the actions column
4. Confirm deletion in the popup dialog

## User Administration

### Viewing Users
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Features**:
- Search by username, full name, or email
- Filter by role
- Sort by name, role, or registration date
- Pagination for large user lists

**Role-Specific Access**:
- Company-Admin: Only users in their company
- WH-Admin: Only users in their company
- SYS-Admin: All users across all companies

### Adding Users
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Admin" > "Users"
2. Click the "Add User" button
3. Fill in user details:
   - Full name
   - Username
   - Email address
   - Role (based on permissions)
4. Click "Create User" to register the account

**Role-Specific Restrictions**:
- Company-Admin: Can only create users in their company
- WH-Admin: Can only create users in their company
- SYS-Admin: Can create users in any company

### Editing User Roles
**Available to**: SYS-Admin, Company-Admin

**Process**:
1. Navigate to "Admin" > "Users"
2. Find the user you want to modify
3. Click the "Edit Role" button
4. Select a new role from the dropdown
5. Click "Update Role" to save changes

**Role-Specific Restrictions**:
- Users cannot change their own role
- Company-Admin can only modify users in their company
- Cannot assign SYS-Admin role (reserved for system administrators)

### Updating User Information
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Admin" > "Users"
2. Find the user you want to modify
3. Click either "Edit Username" or "Edit Email"
4. Enter the new information
5. Click "Update" to save changes

**Role-Specific Restrictions**:
- Users can update their own information
- Administrators can update information for users in their company
- SYS-Admin can update information for any user

### Deleting Users
**Available to**: SYS-Admin, Company-Admin

**Process**:
1. Navigate to "Admin" > "Users"
2. Find the user you want to delete
3. Click the "Delete" button
4. Confirm deletion in the popup dialog

**Role-Specific Restrictions**:
- Users cannot delete themselves
- Company-Admin can only delete users in their company
- SYS-Admin can delete any user

## Company Management

### Viewing Companies
**Available to**: SYS-Admin

**Features**:
- List all registered companies
- View company details including franchise names and logos
- Search by company name
- Sort by name or creation date

### Adding Companies
**Available to**: SYS-Admin

**Process**:
1. Navigate to "Companies" > "View Companies"
2. Click the "Add Company" button
3. Fill in company details:
   - Company name (must be unique)
   - Franchise name (optional)
   - Upload company logo (optional)
4. Click "Create Company" to register

### Editing Companies
**Available to**: SYS-Admin

**Process**:
1. Navigate to "Companies" > "View Companies"
2. Find the company you want to edit
3. Click the "Edit" button
4. Modify company details as needed
5. Click "Update Company" to save changes

### Deleting Companies
**Available to**: SYS-Admin

**Process**:
1. Navigate to "Companies" > "View Companies"
2. Find the company you want to delete
3. Click the "Delete" button
4. Confirm deletion in the popup dialog

**Restrictions**:
- Cannot delete company with existing users
- Cannot delete current user's company

## Activity Logs

### Viewing Activity Logs
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Features**:
- Filter by action type (Add Stock, Remove Stock, etc.)
- Filter by date range
- Search by user or action details
- Sort by timestamp or user
- Pagination for large log sets

**Role-Specific Access**:
- SYS-Admin: Can filter by company and view all logs
- Company-Admin: Only logs from their company
- WH-Admin: Only logs from their company

### Deleting Logs
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Logs" > "Activity Logs"
2. Select logs to delete using checkboxes
3. Click "Delete Selected" button
4. Confirm deletion in the popup dialog

**Role-Specific Restrictions**:
- Users can only delete logs from their company
- SYS-Admin can delete logs from any company

### Clearing All Logs
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to "Logs" > "Activity Logs"
2. Click "Delete All Logs" button
3. Optionally apply filters to limit which logs are deleted
4. Confirm deletion in the popup dialog

**Role-Specific Restrictions**:
- Users can only delete logs from their company
- SYS-Admin can delete logs from any company

## Stock Audits

### Performing Stock Audits
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Misc" > "Stock Audit"
2. Search for products by barcode or name
3. Enter actual quantities observed during physical count
4. System automatically calculates discrepancies
5. Click "Submit Audit" to record results

### Viewing Audit History
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Features**:
- Filter by date range
- Search by product name or audit batch
- Sort by date or discrepancy amount
- Pagination for large audit sets

**Role-Specific Access**:
- SYS-Admin: All audits across all companies
- WH-Admin: Audits from their company
- Company-Admin: Audits from their company

### Generating Audit Reports
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Misc" > "Audit History"
2. Select the audit batch you want to report on
3. Click "Generate Report" button
4. Download the Excel report for further analysis

### Settling Discrepancies
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Misc" > "Audit History"
2. Find an audit with discrepancies
3. Click "Settle Discrepancy" button
4. Confirm that you want to adjust inventory to match audit results
5. System updates inventory levels and logs the adjustment

## Pending Removals

### Requesting Stock Removal
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Pending Removals" > "View Pending Removals"
2. Click "Submit Removal Request" button
3. Search for the product with stock to remove
4. Enter quantity to remove
5. Provide reason for removal (expired, damaged, etc.)
6. Add any additional remarks
7. Click "Submit Request" to create pending removal

### Reviewing Removal Requests
**Available to**: SYS-Admin, WH-Admin

**Process**:
1. Navigate to "Pending Removals" > "View Pending Removals"
2. Find the request to review
3. Click "Review" button
4. Choose to "Approve" or "Reject" the request
5. If rejecting, provide reason for rejection
6. Click "Submit Review" to process

**For Approved Requests**:
- System removes the specified quantity from inventory
- Updates request status to "Approved"
- Logs the removal activity

**For Rejected Requests**:
- System does not modify inventory
- Updates request status to "Rejected"
- Logs the rejection with provided reason

### Viewing Removal History
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Features**:
- Filter by date range
- Filter by status (Approved, Rejected)
- Search by product name or requester
- Sort by date or status
- Pagination for large history sets

**Role-Specific Access**:
- SYS-Admin: All removals across all companies
- WH-Admin: Removals from their company
- Company-Admin: Removals from their company

## Scanner Functions

### Mobile Scanner
**Available to**: SYS-Admin, WH-Admin, Company-Admin (mobile devices only)

**Features**:
- Barcode scanning using device camera
- Quick add/remove stock functionality
- Mobile-optimized interface
- Offline capability for basic functions

**Process**:
1. Navigate to "Scanner" > "Mobile Scanner" on a mobile device
2. Allow camera access when prompted
3. Point camera at barcode to scan
4. System displays product information
5. Choose to add or remove stock
6. Enter quantity and confirm transaction

### Scan Add Stock
**Available to**: SYS-Admin, WH-Admin (mobile devices only)

**Process**:
1. Navigate to "Scanner" > "Add Stock" on a mobile device
2. Scan the product barcode
3. Enter quantity to add
4. Provide supplier information (optional)
5. Click "Add Stock" to update inventory

### Scan Remove Stock
**Available to**: SYS-Admin, WH-Admin (mobile devices only)

**Process**:
1. Navigate to "Scanner" > "Remove Stock" on a mobile device
2. Scan the product barcode
3. Enter quantity to remove
4. Provide reason for removal (optional)
5. Click "Remove Stock" to update inventory

## Reports and Analytics

### Daily Reports
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Process**:
1. Navigate to Dashboard
2. Click "Send Daily Report" button
3. System generates and emails a report with:
   - Low stock items
   - Out of stock items
   - Expired products
   - Expiring products (3 months)

**Role-Specific Content**:
- Company-Admin: Only data from their company
- WH-Admin: Data from their company
- SYS-Admin: Data from all companies (or assigned company)

### Purchaser Reports
**Available to**: Purchaser

**Process**:
1. Navigate to Dashboard
2. Click "Send Purchaser Report" button
3. System generates and emails a report with:
   - Low stock items
   - Out of stock items
   - Expired products
   - Expiring products (3 months)

### Exporting Product Data
**Available to**: All authenticated users except Unverified Users

**Process**:
1. Navigate to "Products" > "View Products"
2. Apply any desired filters
3. Click "Export Products" button
4. Download the Excel file with current product data

**Role-Specific Content**:
- Company-Admin, Purchaser: Only products from their company
- WH-Admin: Products from their company
- SYS-Admin: All products (or assigned company)

### Stock Movement Analytics
**Available to**: SYS-Admin, WH-Admin, Company-Admin

**Features**:
- View stock additions and removals over time
- Filter by time period (week, month, year)
- Visual charts showing trends
- Export data for further analysis

## Role-Specific Workflows and Scenarios

### For SYS-Admin Users

#### Scenario 1: Setting Up a New Company
1. Log in as SYS-Admin
2. Navigate to "Companies" > "View Companies"
3. Click "Add Company" button
4. Fill in company details (name, franchise name, logo)
5. Click "Create Company"
6. Navigate to "Admin" > "Users"
7. Click "Add User" button
8. Create users for the new company (WH-Admin, Company-Admin, etc.)
9. Assign appropriate roles to each user

#### Scenario 2: Monitoring System-Wide Inventory
1. Log in as SYS-Admin
2. View the dashboard for system-wide metrics
3. Check "Low Stock" and "No Stocks" cards for alerts
4. Navigate to "Products" > "View Products" to see all products
5. Use filters to identify products needing attention
6. Generate reports for analysis

#### Scenario 3: Performing System Maintenance
1. Log in as SYS-Admin
2. Navigate to "Logs" > "Activity Logs"
3. Review recent activities for any anomalies
4. Navigate to "Misc" > "Audit History"
5. Review audit results and settle discrepancies if needed
6. Navigate to "Pending Removals" > "View Pending Removals"
7. Review and approve/reject pending removal requests

### For WH-Admin Users

#### Scenario 1: Receiving New Stock Shipment
1. Log in as WH-Admin
2. Navigate to "Products" > "View Products"
3. Find the product that arrived in the shipment
4. Click "Add Stock" button for that product
5. Enter the quantity received
6. Add supplier information if needed
7. Click "Add Stock" to update inventory
8. Verify the stock was added by checking the product history

#### Scenario 2: Processing Requisition Requests
1. Log in as WH-Admin
2. Navigate to "Requisitions" > "View Requisitions"
3. Review pending requisitions
4. Click "Approve" for valid requests with sufficient stock
5. Click "Reject" for invalid requests with reason
6. For approved requests, print delivery forms if needed
7. Monitor stock levels after processing

#### Scenario 3: Handling Expired Products
1. Log in as WH-Admin
2. Check the dashboard for expired product alerts
3. Navigate to "Pending Removals" > "View Pending Removals"
4. Click "Submit Removal Request"
5. Search for the expired product
6. Enter quantity to remove and reason (expired)
7. Submit the request
8. Have another admin review and approve the request

### For Company-Admin Users

#### Scenario 1: Managing Company Users
1. Log in as Company-Admin
2. Navigate to "Admin" > "Users"
3. View current users in your company
4. Click "Add User" to create new users
5. Edit user roles as needed
6. Delete users who are no longer with the company

#### Scenario 2: Monitoring Company Inventory
1. Log in as Company-Admin
2. View the dashboard for company-specific metrics
3. Check "Low Stock" alerts
4. Navigate to "Products" > "View Products" to see all company products
5. Use filters to identify products needing attention
6. Generate reports for company analysis

#### Scenario 3: Reviewing Activity Logs
1. Log in as Company-Admin
2. Navigate to "Logs" > "Activity Logs"
3. Review recent activities within your company
4. Filter by date range or action type as needed
5. Export logs if needed for compliance purposes

### For Purchaser Users

#### Scenario 1: Monitoring Stock Levels
1. Log in as Purchaser
2. View the dashboard for inventory overview
3. Check "Low Stock" alerts
4. Navigate to "Products" > "View Products" to see all company products
5. Use filters to identify products needing replenishment

#### Scenario 2: Generating Purchase Orders
1. Log in as Purchaser
2. Navigate to "Products" > "View Products"
3. Identify low stock items that need replenishment
4. Note current stock levels and reorder levels
5. Generate reports to share with suppliers
6. Use the "Export Products" feature to create detailed lists

#### Scenario 3: Receiving Automated Reports
1. Ensure your email address is correctly configured
2. Receive daily/weekly reports automatically
3. Review reports for low stock and expiring items
4. Coordinate with WH-Admin for stock replenishment

### For Regular Users

#### Scenario 1: Submitting Requisition Requests
1. Log in as User
2. Navigate to "Requisitions" > "New Requisition"
3. Search for products needed
4. Add items to requisition with quantities
5. Review the requisition before submitting
6. Click "Submit Requisition"
7. Check requisition status in "Requisitions" > "View Requisitions"

#### Scenario 2: Tracking Requisition Status
1. Log in as User
2. Navigate to "Requisitions" > "View Requisitions"
3. View all submitted requisitions
4. Check status (Pending, Approved, Rejected)
5. For approved requisitions, coordinate with warehouse for pickup

## Troubleshooting

### Common Issues and Solutions

#### Login Problems
**Issue**: Cannot log in to the system
**Solutions**:
1. Verify username and password are correct
2. Check that caps lock is off
3. If you've forgotten your password, use the "Forgot Password" link
4. If you're a new user, check your email for verification link
5. Contact your system administrator if problems persist

#### Barcode Scanning Issues
**Issue**: Mobile scanner not working properly
**Solutions**:
1. Ensure you're using a mobile device (not desktop)
2. Allow camera access when prompted
3. Ensure good lighting conditions
4. Hold device steady and close to barcode
5. Clean camera lens if necessary
6. Try manually entering barcode if scanning continues to fail

#### Report Generation Failures
**Issue**: Reports not being generated or sent
**Solutions**:
1. Check that your email address is correctly configured
2. Verify that the system email settings are correct (admin only)
3. Try generating the report again
4. Check spam/junk folder for delivered reports
5. Contact system administrator if problems persist

#### Slow Performance
**Issue**: System responding slowly
**Solutions**:
1. Refresh the page
2. Clear browser cache and cookies
3. Try a different browser
4. Check internet connection speed
5. Contact system administrator if problems persist

#### Data Not Updating
**Issue**: Changes not appearing in the system
**Solutions**:
1. Refresh the page to see updates
2. Check that you have the necessary permissions for the action
3. Verify that all required fields were completed
4. Check activity logs to see if the action was recorded
5. Contact system administrator if problems persist

### Contact Support
If you continue to experience issues not addressed in this manual, please contact your system administrator or the support team at [support email/phone number].
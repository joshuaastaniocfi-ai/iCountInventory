# iCount Inventory Management System - Complete Function Documentation

## Table of Contents
1. [User Roles and Permissions](#user-roles-and-permissions)
2. [Authentication Functions](#authentication-functions)
3. [Dashboard Functions](#dashboard-functions)
4. [Product Management Functions](#product-management-functions)
5. [Requisition Functions](#requisition-functions)
6. [User Administration Functions](#user-administration-functions)
7. [Company Management Functions](#company-management-functions)
8. [Activity Log Functions](#activity-log-functions)
9. [Stock Audit Functions](#stock-audit-functions)
10. [Pending Removals Functions](#pending-removals-functions)
11. [Scanner Functions](#scanner-functions)
12. [API Functions](#api-functions)
13. [Miscellaneous Functions](#miscellaneous-functions)
14. [Role-Based Access Control Matrix](#role-based-access-control-matrix)
15. [Common Scenarios and Workflows](#common-scenarios-and-workflows)

## User Roles and Permissions

The system has 6 distinct user roles with varying levels of access:

### 1. SYS-Admin (System Administrator)
- **Highest privilege level**
- Can manage all companies, users, and system-wide settings
- Can view all data across all companies
- Can perform all administrative functions
- Can delete any records in the system
- Can assign roles to users
- Can manage company configurations

### 2. WH-Admin (Warehouse Administrator)
- **Company-specific admin role**
- Can manage products, users, and settings within their assigned company
- Can approve/reject requisitions and pending removals
- Can perform stock audits
- Can add/remove stock
- Cannot delete companies or other WH-Admins/SYS-Admins

### 3. Company-Admin (Company Administrator)
- **Company-specific admin role**
- Can manage users within their company
- Can view reports and activity logs for their company
- Can update their own profile information
- Cannot modify inventory quantities
- Can view product information but not edit

### 4. Purchaser
- **Company-specific role**
- Can view products and inventory levels
- Can generate reports
- Cannot make changes to inventory
- Cannot process requisitions
- Can view low stock alerts and expiring products

### 5. User (Regular User)
- **Company-specific role**
- Can submit requisitions only
- Cannot access administrative functions
- Redirected to requisition form upon login
- Can view their own requisition history

### 6. Unverified User
- **Limited access until email verification**
- Cannot log in until email is verified
- Created during signup process

## Authentication Functions

### Signup (`/signup`)
- **Access**: Public (no login required)
- **Description**: Allows new users to register for an account
- **Process**:
  1. User fills out registration form with personal details
  2. System validates uniqueness of username and email
  3. System assigns role based on username:
     - 'admin' → SYS-Admin (auto-verified)
     - 'wh-admin' → WH-Admin (auto-verified)
     - All other usernames → Regular User (requires email verification)
  4. System sends verification email to non-admin users
  5. System notifies admins of new user registration

### Login (`/login`)
- **Access**: Public
- **Description**: Authenticates users and redirects based on role
- **Process**:
  1. User provides credentials
  2. System validates credentials and email verification status
  3. System redirects based on role:
     - User → Requisition form
     - Admin roles → Dashboard (mobile users get scanner view)

### Logout (`/logout`)
- **Access**: Authenticated users only
- **Description**: Ends user session
- **Process**: Clears session and redirects to login page

### Email Verification (`/verify_email/<token>`)
- **Access**: Public (token required)
- **Description**: Verifies user email address
- **Process**:
  1. Validates verification token
  2. Marks user as email verified
  3. Redirects to appropriate dashboard

### Forgot Password (`/forgot_password`)
- **Access**: Public
- **Description**: Initiates password reset process
- **Process**:
  1. User provides email address
  2. System sends password reset link if email exists
  3. User clicks link to reset password

### Reset Password (`/reset_password/<token>`)
- **Access**: Public (token required)
- **Description**: Allows user to set new password
- **Process**:
  1. Validates reset token
  2. Allows user to set new password
  3. Updates password in database

## Dashboard Functions

### Main Dashboard (`/`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin, Purchaser
- **Description**: Central hub displaying key inventory metrics
- **Features**:
  - Inventory summary (total items, low stock, out of stock)
  - Requisition statistics (total, pending)
  - Expiring products (30-day and 3-month views)
  - Expired products
  - Favorite products
  - Recent activity logs
  - Weekly stock movement chart
  - Top stocked products

### Send Weekly Report (`/send_weekly_report`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Generates and emails inventory report
- **Process**:
  - For Company-Admin: Filters data to their company only
  - For SYS-Admin and WH-Admin: Shows all data (or company-specific if assigned)
  - Sends detailed HTML email with inventory status
  - Report includes low stock items, out of stock items, expired products, and expiring products

### Generate Weekly Report (`/generate_weekly_report`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Generates downloadable inventory report
- **Process**:
  - Creates Excel file with inventory data
  - For Company-Admin: Filters data to their company only
  - Provides download link for report

## Product Management Functions

### View Products (`/products/products`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin, Purchaser
- **Description**: Displays paginated list of products
- **Features**:
  - Search by name, account title, or barcode
  - Filter by account type, status (OK, Low Stock, No Stock, etc.)
  - For SYS-Admin: Filter by company
  - Sort by name (alphabetical)
  - Export to Excel functionality

### Add Product (`/products/add_product`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Adds new product to inventory
- **Process**:
  1. Generates unique barcode
  2. Assigns to current user's company
  3. Creates product record with initial stock
  4. Supports setting reorder level and low stock threshold

### Edit Product (`/products/edit_product/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Updates existing product information
- **Restrictions**:
  - Users can only edit products in their company
  - SYS-Admin can edit any product
  - Supports updating reorder level, low stock threshold, and other product details

### Delete Product (`/products/delete_product/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Removes product from inventory
- **Restrictions**:
  - Users can only delete products in their company
  - SYS-Admin can delete any product
  - Deletes all associated batches, history, and requisition items

### Toggle Favorite (`/products/toggle_favorite/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin, Purchaser
- **Description**: Marks/unmarks product as favorite
- **Restrictions**: Users can only toggle favorites for products in their company
- **Usage**: Favorite products appear in the dashboard for quick access

### Add Stock (`/products/add_stock/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Increases product quantity
- **Process**:
  1. Adds stock to existing batches or creates new batch
  2. Records transaction in product history
  3. Logs activity
  4. Updates last_updated timestamp

### Remove Stock (`/products/remove_stock/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Decreases product quantity
- **Process**:
  1. Removes stock from batches (FIFO method)
  2. Records transaction in product history
  3. Logs activity
  4. Updates last_updated timestamp

### View Product History (`/products/product_history/<int:product_id>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin, Purchaser
- **Description**: Shows transaction history for a product
- **Features**:
  - Displays all TRANS IN and TRANS OUT transactions
  - Shows quantity changes over time
  - Includes reference information (requisitions, batches)

### Import Products (`/products/import_products`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Bulk imports products from Excel/CSV file
- **Process**:
  1. Validates file format
  2. Processes each row as new product
  3. Assigns to current user's company
  4. Generates success/failure report
  5. Supports setting reorder levels during import

### Export Products (`/products/export_products`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin, Purchaser
- **Description**: Exports product list to Excel file
- **Process**:
  1. For Company-Admin/Purchaser: Exports only their company's products
  2. For SYS-Admin/WH-Admin: Exports all products (or company-specific if assigned)
  3. Generates downloadable Excel file

## Requisition Functions

### Requisition Form (`/requisitions/requisition_form`)
- **Access**: User, SYS-Admin, WH-Admin, Company-Admin
- **Description**: Interface for creating new requisitions
- **Features**:
  - Search products by name
  - Add items with quantity and UOM
  - Local storage persistence
  - Company-specific product filtering

### Submit Requisition (`/requisitions/submit_requisition`)
- **Access**: User
- **Description**: Submits requisition for approval
- **Process**:
  1. Creates requisition record
  2. Associates items with requisition
  3. Assigns to user's company
  4. Sends confirmation email to user
  5. Logs activity

### View Requisitions (`/requisitions/view_requisitions`)
- **Access**: All authenticated users
- **Description**: Displays list of requisitions
- **Features**:
  - Pagination and search
  - Filter by status
  - Role-based visibility:
    - User: Only their own requisitions
    - Company-Admin: Requisitions from their company
    - WH-Admin: Requisitions from their company
    - SYS-Admin: All requisitions

### Update Requisition Status (`/requisitions/update_status/<int:requisition_id>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Approves or rejects requisitions
- **Process**:
  1. Updates requisition status
  2. For approved requisitions: Deducts stock from inventory
  3. Sends status update email to requester
  4. Logs activity

### Print Delivery Form (`/requisitions/print_delivery_form/<int:requisition_id>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Generates printable delivery form
- **Restrictions**: Only for approved requisitions

### Delete Requisition (`/requisitions/delete_requisition/<int:requisition_id>`)
- **Access**: SYS-Admin
- **Description**: Permanently removes requisition
- **Restrictions**: Only approved or rejected requisitions can be deleted

## User Administration Functions

### View Users (`/admin/users`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Displays list of users
- **Features**:
  - Pagination and search
  - Role-based visibility:
    - Company-Admin: Only users in their company
    - WH-Admin: Only users in their company
    - SYS-Admin: All users (or company-specific if assigned)

### Update User Role (`/admin/users/<int:user_id>/role`)
- **Access**: SYS-Admin, Company-Admin
- **Description**: Changes user's role
- **Restrictions**:
  - Users cannot change their own role
  - Company-Admin can only modify users in their company
  - Cannot assign SYS-Admin role

### Update Username (`/admin/users/<int:user_id>/username`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Changes user's username
- **Restrictions**: Users can only update their own username

### Update Email (`/admin/users/<int:user_id>/email`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Changes user's email address
- **Restrictions**: Users can only update their own email

### Delete User (`/admin/users/<int:user_id>/delete`)
- **Access**: SYS-Admin, Company-Admin
- **Description**: Removes user from system
- **Restrictions**:
  - Users cannot delete themselves
  - Company-Admin can only delete users in their company

## Company Management Functions

### View Companies (`/companies/companies`)
- **Access**: SYS-Admin
- **Description**: Displays list of all companies
- **Features**: Shows company details including franchise names and logos

### Add Company (`/companies/add_company`)
- **Access**: SYS-Admin
- **Description**: Creates new company
- **Process**:
  1. Validates unique company name
  2. Handles company logo upload
  3. Creates company record

### Edit Company (`/companies/edit_company/<int:company_id>`)
- **Access**: SYS-Admin
- **Description**: Updates company information
- **Process**:
  1. Validates unique company name
  2. Handles company logo upload/replacement
  3. Updates company record

### Delete Company (`/companies/delete_company/<int:company_id>`)
- **Access**: SYS-Admin
- **Description**: Removes company from system
- **Restrictions**:
  - Cannot delete company with existing users
  - Cannot delete current user's company

## Activity Log Functions

### View Activity Logs (`/logs/activity_logs`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Displays system activity history
- **Features**:
  - Pagination and search
  - Filter by action type, date
  - For SYS-Admin: Filter by company
  - Company-Admin: Only logs from their company

### Delete Logs (`/logs/delete_logs`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Removes selected activity logs
- **Restrictions**: Users can only delete logs from their company

### Delete All Logs (`/logs/delete_all_logs`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Removes all activity logs (with optional filters)
- **Restrictions**: Users can only delete logs from their company

## Stock Audit Functions

### Stock Audit Dashboard (`/misc/stock_audit`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Interface for performing stock audits
- **Features**:
  - Search products by barcode or name
  - Record actual quantities
  - Identify discrepancies

### Submit Stock Audit (`/misc/submit_audit`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Records results of stock audit
- **Process**:
  1. Calculates discrepancies
  2. Creates audit record
  3. Updates product quantities if discrepancies found
  4. Logs activity

### View Audit History (`/misc/audit_history`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Displays history of stock audits
- **Features**:
  - Pagination and search
  - Filter by date range
  - Company-Admin: Only audits from their company

### Generate Audit Report (`/misc/generate_audit_report`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Creates detailed audit report
- **Process**: Generates downloadable Excel file with audit data

### Settle Discrepancy (`/misc/settle_discrepancy/<int:audit_id>`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Marks audit discrepancy as resolved
- **Process**: Updates audit record status

## Pending Removals Functions

### View Pending Removals (`/pending_removals/view_pending_removals`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Displays requests to remove expired/unsellable stock
- **Features**:
  - Filter by status (Pending, Approved, Rejected)
  - Company-Admin: Only removals from their company

### Submit Removal Request (`/pending_removals/submit_removal_request`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Requests approval to remove stock
- **Process**:
  1. Creates pending removal record
  2. Assigns to current user's company
  3. Logs activity

### Review Removal Request (`/pending_removals/review_removal/<int:removal_id>`)
- **Access**: SYS-Admin, WH-Admin
- **Description**: Approves or rejects removal request
- **Process**:
  1. Updates removal status
  2. For approved requests: Removes stock from inventory
  3. Logs activity

### View Removal History (`/pending_removals/removal_history`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Displays history of removal requests
- **Features**:
  - Filter by date range and status
  - Company-Admin: Only removals from their company

## Scanner Functions

### Mobile Scanner (`/scanner/mobile_scanner`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin (mobile devices)
- **Description**: Mobile interface for scanning products
- **Features**:
  - Barcode scanning
  - Quick add/remove stock
  - Mobile-optimized interface

### Scan Add Stock (`/scanner/scan_add_stock`)
- **Access**: SYS-Admin, WH-Admin (mobile devices)
- **Description**: Mobile interface for adding stock via scanning
- **Process**:
  1. Scans product barcode
  2. Enters quantity to add
  3. Records transaction

### Scan Remove Stock (`/scanner/scan_remove_stock`)
- **Access**: SYS-Admin, WH-Admin (mobile devices)
- **Description**: Mobile interface for removing stock via scanning
- **Process**:
  1. Scans product barcode
  2. Enters quantity to remove
  3. Records transaction

## API Functions

### Get Product Info (`/api/product_info/<barcode>`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Returns product information for barcode
- **Process**: JSON response with product details

### Get Low Stock Products (`/api/low_stock_products`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Returns list of low stock products
- **Process**: JSON response with product data

### Get Expiring Products (`/api/expiring_products`)
- **Access**: SYS-Admin, WH-Admin, Company-Admin
- **Description**: Returns list of expiring products
- **Process**: JSON response with product data

## Miscellaneous Functions

### Error Pages (404, 500)
- **Access**: All users
- **Description**: Custom error pages for common HTTP errors

### Health Check
- **Access**: System use
- **Description**: Verifies system functionality

### Configuration Management
- **Access**: System use
- **Description**: Manages application settings and environment variables

## Role-Based Access Control Matrix

| Function | SYS-Admin | WH-Admin | Company-Admin | Purchaser | User |
|----------|-----------|----------|---------------|-----------|------|
| View Dashboard | ✓ | ✓ | ✓ | ✓ | → Requisition Form |
| View Products | ✓ (All) | ✓ (Company) | ✓ (Company) | ✓ (Company) | ✗ |
| Add Product | ✓ | ✓ | ✓ | ✗ | ✗ |
| Edit Product | ✓ (All) | ✓ (Company) | ✓ (Company) | ✗ | ✗ |
| Delete Product | ✓ (All) | ✓ (Company) | ✗ | ✗ | ✗ |
| Add Stock | ✓ | ✓ | ✗ | ✗ | ✗ |
| Remove Stock | ✓ | ✓ | ✗ | ✗ | ✗ |
| View Product History | ✓ | ✓ | ✓ | ✓ | ✗ |
| Import Products | ✓ | ✓ | ✗ | ✗ | ✗ |
| Export Products | ✓ | ✓ | ✓ | ✓ | ✗ |
| Submit Requisition | ✓ | ✓ | ✓ | ✗ | ✓ |
| Approve Requisitions | ✓ | ✓ | ✓ | ✗ | ✗ |
| View Requisitions | ✓ (All) | ✓ (Company) | ✓ (Company) | ✗ | ✓ (Own) |
| View Users | ✓ (All) | ✓ (Company) | ✓ (Company) | ✗ | ✗ |
| Add Users | ✓ | ✓ | ✓ | ✗ | ✗ |
| Edit Users | ✓ | ✓ | ✓ | ✗ | ✓ (Own) |
| Delete Users | ✓ | ✗ | ✓ | ✗ | ✗ |
| View Companies | ✓ | ✗ | ✗ | ✗ | ✗ |
| Manage Companies | ✓ | ✗ | ✗ | ✗ | ✗ |
| View Activity Logs | ✓ (All) | ✓ (Company) | ✓ (Company) | ✗ | ✗ |
| Stock Audits | ✓ | ✓ | ✗ | ✗ | ✗ |
| Pending Removals | ✓ | ✓ | ✓ (View) | ✗ | ✗ |
| Mobile Scanner | ✓ | ✓ | ✓ | ✗ | ✗ |

## Common Scenarios and Workflows

### Scenario 1: New Product Registration
**Roles Involved**: SYS-Admin, WH-Admin, Company-Admin
**Workflow**:
1. Admin navigates to "Products" > "Add Product"
2. Fills in product details including name, account title, UOM, initial quantity
3. Sets reorder level and low stock threshold
4. System generates unique barcode
5. Product is added to inventory and assigned to admin's company

### Scenario 2: Stock Replenishment
**Roles Involved**: SYS-Admin, WH-Admin
**Workflow**:
1. Admin receives new stock shipment
2. Navigates to "Products" > "View Products"
3. Finds product to replenish
4. Clicks "Add Stock" button
5. Enters quantity received and supplier information
6. System updates inventory levels and logs transaction

### Scenario 3: Requisition Processing
**Roles Involved**: User, SYS-Admin, WH-Admin, Company-Admin
**Workflow**:
1. User submits requisition through "Requisitions" > "New Requisition"
2. Admin reviews pending requisitions in "Requisitions" > "View Requisitions"
3. Admin approves or rejects requisition
4. If approved, system deducts stock and sends confirmation to user
5. Admin can print delivery form for approved requisitions

### Scenario 4: Stock Audit Process
**Roles Involved**: SYS-Admin, WH-Admin
**Workflow**:
1. Admin performs physical inventory count
2. Navigates to "Misc" > "Stock Audit"
3. Enters actual quantities observed
4. System calculates discrepancies
5. Admin submits audit results
6. For significant discrepancies, admin can settle them to adjust inventory

### Scenario 5: Expired Product Removal
**Roles Involved**: SYS-Admin, WH-Admin
**Workflow**:
1. System alerts admin to expiring products on dashboard
2. Admin reviews expiring products
3. For expired/unsellable items, admin submits removal request
4. Request is reviewed and approved by another admin
5. System removes stock and logs the transaction

### Scenario 6: Reporting and Analytics
**Roles Involved**: All roles (with varying access)
**Workflow**:
1. Users can view dashboard metrics relevant to their role
2. Admins can generate detailed reports
3. Purchasers receive automated reports
4. SYS-Admins can view system-wide analytics
5. All users can export relevant data to Excel
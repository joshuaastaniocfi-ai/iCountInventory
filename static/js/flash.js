// Show notification alert
function showAlert(message, type = 'success') {
    // Create container if it doesn't exist
    let container = document.querySelector('.alert-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'alert-container';
        document.body.appendChild(container);
    }

    // Detect if we're in the dashboard (has sidebar) or auth pages
    const isDashboard = document.querySelector('#sidebar') !== null;
    const themeClass = isDashboard ? 'light-theme' : 'dark-theme';

    // Create alert element
    const alert = document.createElement('div');
    alert.className = `alert-popup alert-${type} ${themeClass} slide-in-right`;
    
    // Get icon based on type
    const icon = type === 'success' ? 'check-circle' :
                type === 'danger' ? 'times-circle' :
                type === 'warning' ? 'exclamation-triangle' :
                'info-circle';
    
    alert.innerHTML = `
        <div class="alert-content">
            <i class="fas fa-${icon} alert-icon"></i>
            <span class="alert-message">${message}</span>
        </div>
        <button type="button" class="alert-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;

    // Add to container
    container.appendChild(alert);

    // Auto remove after delay
    setTimeout(() => {
        alert.classList.add('slide-out-right');
        setTimeout(() => alert.remove(), 300);
    }, 5000);
}

// Add styles to document
const styles = document.createElement('style');
styles.textContent = `
    .alert-container {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        display: flex;
        flex-direction: column;
        gap: 10px;
        max-width: 400px;
    }

    .alert-popup {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        margin-bottom: 10px;
    }

    /* Light theme (Dashboard) */
    .alert-popup.light-theme {
        background: #ffffff;
        color: #2a2d31;
    }

    .alert-popup.light-theme .alert-close {
        color: #2a2d31;
    }

    /* Dark theme (Login/Signup) */
    .alert-popup.dark-theme {
        background: #2a2d31;
        color: #ffffff;
    }

    .alert-popup.dark-theme .alert-close {
        color: #ffffff;
    }

    .alert-content {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .alert-icon {
        font-size: 20px;
    }

    .alert-message {
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        font-weight: 500;
    }

    .alert-close {
        background: none;
        border: none;
        padding: 4px;
        cursor: pointer;
        opacity: 0.6;
        transition: opacity 0.2s;
    }

    .alert-close:hover {
        opacity: 1;
    }

    .alert-success {
        border-left: 4px solid #10b981;
    }
    .alert-success .alert-icon {
        color: #10b981;
    }

    .alert-danger {
        border-left: 4px solid #ef4444;
    }
    .alert-danger .alert-icon {
        color: #ef4444;
    }

    .alert-warning {
        border-left: 4px solid #f59e0b;
    }
    .alert-warning .alert-icon {
        color: #f59e0b;
    }

    .alert-info {
        border-left: 4px solid #6366f1;
    }
    .alert-info .alert-icon {
        color: #6366f1;
    }

    /* Animations */
    .slide-in-right {
        animation: slideInRight 0.3s forwards;
    }

    .slide-out-right {
        animation: slideOutRight 0.3s forwards;
    }

    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(styles);

// Handle existing flash messages on page load
document.addEventListener('DOMContentLoaded', function() {
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(function(flash) {
        // Get the category and message
        const category = Array.from(flash.classList)
            .find(cls => ['success', 'danger', 'warning', 'info'].includes(cls)) || 'info';
        const message = flash.querySelector('.flash-content').textContent;
        
        // Remove the original flash message
        flash.remove();
        
        // Show as alert
        showAlert(message, category);
    });
});
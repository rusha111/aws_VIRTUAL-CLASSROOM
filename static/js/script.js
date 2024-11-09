// Example form validation for registration
document.querySelector('form').addEventListener('submit', function(e) {
    const password = document.querySelector('input[name="password"]').value;
    if (password.length < 6) {
        e.preventDefault();
        alert("Password must be at least 6 characters long");
    }
});

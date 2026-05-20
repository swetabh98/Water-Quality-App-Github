from app import create_app

# Create your Flask app instance
app = create_app()

if __name__ == '__main__':
    print("✅ Starting Flask app securely at https://localhost:8826")
    app.run(
        host='0.0.0.0',
        port=8826,
        ssl_context=('localhost.pem', 'localhost-key.pem')  # mkcert-generated cert + key
    )
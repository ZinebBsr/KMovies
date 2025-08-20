from app import app

# Vercel needs this function signature
def handler(request, *args, **kwargs):
    return app(request, *args, **kwargs)

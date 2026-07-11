from flask import send_from_directory

@app.route('/.well-known/assetlinks.json')
def assetlinks():
    return send_from_directory('static/.well-known', 'assetlinks.json', mimetype='application/json')

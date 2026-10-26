from app_types import Application


def setup(a:Application):
    global app
    app = a
    @app.route('/parent_dashboard')
    def parent_dashboard():
        pass
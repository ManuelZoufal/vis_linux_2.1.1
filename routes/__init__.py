from flask import Blueprint

# Create Blueprints

# /
root_bp = Blueprint('root', __name__)

## /api
api_bp = Blueprint('api', __name__)

## /admin
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

## /group
group_bp = Blueprint('group', __name__)

## /visualize
visualize_bp = Blueprint('visualize', __name__)



# Import routes
from . import admin, groups, visualize, api, root

# Ensure routes are registered with the blueprints
__all__ = ['root_bp', 'admin_bp', 'group_bp', 'visualize_bp', 'api_bp']

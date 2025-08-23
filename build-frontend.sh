#!/bin/bash

# Build the React frontend and copy to Flask app

set -e  # Exit on error

echo "Building React frontend..."
cd frontend
npm run build
cd ..

echo "Copying build to Flask app..."
rm -rf frontend-dist
cp -r frontend/dist frontend-dist

echo "Frontend build complete! Run your Flask app to serve the React application."
echo "The React app will be served at the root path, with API endpoints under /api/"

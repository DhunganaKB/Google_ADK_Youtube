FROM nginx:alpine

# Replace default nginx config with ours (port 8080 for Cloud Run)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Serve the single-page app
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]

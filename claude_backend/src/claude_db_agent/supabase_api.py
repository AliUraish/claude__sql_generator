"""Supabase Management API client."""

import os
import time
import secrets
import string
from datetime import datetime
from typing import Optional, Dict, Any
import requests


class SupabaseAPIError(Exception):
    """Custom exception for Supabase API errors."""
    pass


class SupabaseManager:
    """Client for Supabase Management API."""
    
    BASE_URL = "https://api.supabase.com/v1"
    
    def __init__(self, access_token: Optional[str] = None):
        """Initialize Supabase API client.
        
        Args:
            access_token: Supabase access token. If not provided, reads from SUPABASE_ACCESS_TOKEN env var.
        """
        self.access_token = access_token or os.getenv("SUPABASE_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError(
                "SUPABASE_ACCESS_TOKEN not found. Please set it in your .env file or environment.\n"
                "Get your token from: https://supabase.com/dashboard/account/tokens"
            )
        
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[Any, Any]:
        """Make a request to the Supabase API.
        
        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests
            
        Returns:
            Response JSON
            
        Raises:
            SupabaseAPIError: If the request fails
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.HTTPError as e:
            error_msg = f"Supabase API error: {e}"
            try:
                error_detail = response.json()
                error_msg += f"\nDetails: {error_detail}"
            except:
                error_msg += f"\nResponse: {response.text}"
            raise SupabaseAPIError(error_msg)
        except requests.exceptions.RequestException as e:
            raise SupabaseAPIError(f"Request failed: {e}")
    
    def list_organizations(self) -> list:
        """List all organizations the user belongs to.
        
        Returns:
            List of organization objects
        """
        return self._request("GET", "/organizations")
    
    def get_default_organization(self) -> Dict[str, Any]:
        """Get the first/default organization.
        
        Returns:
            Organization object
            
        Raises:
            SupabaseAPIError: If no organizations found
        """
        orgs = self.list_organizations()
        if not orgs:
            raise SupabaseAPIError(
                "No organizations found. Please create one at https://supabase.com/dashboard"
            )
        return orgs[0]
    
    def generate_db_password(self, length: int = 32) -> str:
        """Generate a secure random database password.
        
        Args:
            length: Password length
            
        Returns:
            Random password string
        """
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    def create_project(
        self,
        organization_id: str,
        name: Optional[str] = None,
        region: Optional[str] = None,
        db_password: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new Supabase project.
        
        Args:
            organization_id: Organization ID to create project under
            name: Project name (auto-generated if not provided)
            region: AWS region (defaults to us-east-1)
            db_password: Database password (auto-generated if not provided)
            
        Returns:
            Project object
        """
        if name is None:
            name = os.getenv("SUPABASE_PROJECT_NAME")
            if name is None:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                name = f"claude-db-agent-{timestamp}"
        
        if region is None:
            region = os.getenv("SUPABASE_REGION", "us-east-1")
        
        if db_password is None:
            db_password = self.generate_db_password()
        
        payload = {
            "name": name,
            "organization_id": organization_id,
            "region": region,
            "plan": "free",  # Start with free plan
            "db_pass": db_password
        }
        
        print(f"Creating Supabase project '{name}' in {region}...")
        project = self._request("POST", "/projects", json=payload)
        
        # Store password for later use (it's not retrievable via API)
        project["_db_password"] = db_password
        
        return project
    
    def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get project details.
        
        Args:
            project_id: Project ID or project ref
            
        Returns:
            Project object
        """
        return self._request("GET", f"/projects/{project_id}")
    
    def wait_for_project_ready(self, project_id: str, timeout: int = 300, poll_interval: int = 5) -> Dict[str, Any]:
        """Wait for a project to be ready.
        
        Args:
            project_id: Project ID or ref
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks in seconds
            
        Returns:
            Project object when ready
            
        Raises:
            SupabaseAPIError: If project doesn't become ready within timeout
        """
        start_time = time.time()
        print("⏳ Waiting for project to be ready (this may take 1-2 minutes)...")
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise SupabaseAPIError(
                    f"Project did not become ready within {timeout} seconds"
                )
            
            try:
                project = self.get_project(project_id)
                status = project.get("status")
                
                if status == "ACTIVE_HEALTHY":
                    print("✓ Project is ready!")
                    return project
                elif status in ["COMING_UP", "INIT_IN_PROGRESS", "ACTIVE_STARTING"]:
                    print(f"  Status: {status} (waiting...)")
                elif status in ["PAUSED", "PAUSING"]:
                    raise SupabaseAPIError(f"Project is paused: {status}")
                elif status in ["INACTIVE", "REMOVED"]:
                    raise SupabaseAPIError(f"Project creation failed: {status}")
                else:
                    print(f"  Status: {status} (waiting...)")
                
            except SupabaseAPIError as e:
                if "Project did not become ready" in str(e):
                    raise
                # Other errors might be transient during initialization
                print(f"  Temporary error checking status: {e}")
            
            time.sleep(poll_interval)
    
    def get_connection_details(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """Extract database connection details from a project.
        
        Args:
            project: Project object (must include _db_password)
            
        Returns:
            Dictionary with connection details
        """
        project_ref = project.get("id")
        db_password = project.get("_db_password")
        
        if not db_password:
            raise ValueError(
                "Database password not found. This should have been set during project creation."
            )
        
        # Construct connection details
        db_host = f"db.{project_ref}.supabase.co"
        db_port = 5432
        db_name = "postgres"
        db_user = "postgres"
        
        connection_string = (
            f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        )
        
        api_url = f"https://{project_ref}.supabase.co"
        
        return {
            "project_id": project_ref,
            "project_name": project.get("name"),
            "region": project.get("region"),
            "db_host": db_host,
            "db_port": db_port,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
            "connection_string": connection_string,
            "api_url": api_url,
            "dashboard_url": f"https://supabase.com/dashboard/project/{project_ref}"
        }
    
    def save_credentials(self, connection_details: Dict[str, Any], output_path: str = "./out/supabase_credentials.json") -> str:
        """Save connection credentials to a file.
        
        Args:
            connection_details: Connection details dictionary
            output_path: Path to save credentials file
            
        Returns:
            Path to saved file
        """
        import json
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(connection_details, f, indent=2)
        
        # Set restrictive permissions
        try:
            os.chmod(output_path, 0o600)
        except:
            pass  # May fail on Windows
        
        return output_path

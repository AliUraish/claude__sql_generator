#!/usr/bin/env python3
"""Verify that the Claude DB Agent is properly set up."""

import os
import sys


def check_env_file():
    """Check if .env file exists and has required keys."""
    print("Checking .env file...")
    
    if not os.path.exists(".env"):
        print("  ⚠️  No .env file found")
        print("  → Run: cp .env.example .env")
        return False
    
    print("  ✓ .env file exists")
    
    # Try to load it
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        if os.getenv("ANTHROPIC_API_KEY"):
            print("  ✓ ANTHROPIC_API_KEY is set")
        else:
            print("  ⚠️  ANTHROPIC_API_KEY not set in .env")
            return False
        
        if os.getenv("SUPABASE_ACCESS_TOKEN"):
            print("  ✓ SUPABASE_ACCESS_TOKEN is set (optional)")
        else:
            print("  ℹ️  SUPABASE_ACCESS_TOKEN not set (only needed for auto-provisioning)")
        
        return True
    except ImportError:
        print("  ⚠️  python-dotenv not installed")
        return False


def check_dependencies():
    """Check if all required packages are installed."""
    print("\nChecking dependencies...")
    
    required = [
        "anthropic",
        "requests",
        "psycopg2",
        "dotenv",
        "pydantic"
    ]
    
    missing = []
    
    for package in required:
        try:
            if package == "dotenv":
                __import__("dotenv")
            elif package == "psycopg2":
                __import__("psycopg2")
            else:
                __import__(package)
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ✗ {package} (missing)")
            missing.append(package)
    
    if missing:
        print(f"\n  → Run: pip install -r requirements.txt")
        return False
    
    return True


def check_package_structure():
    """Check if the package structure is correct."""
    print("\nChecking package structure...")
    
    required_files = [
        "src/claude_db_agent/__init__.py",
        "src/claude_db_agent/cli.py",
        "src/claude_db_agent/claude_client.py",
        "src/claude_db_agent/schema_model.py",
        "src/claude_db_agent/supabase_api.py",
        "src/claude_db_agent/sql_apply.py",
    ]
    
    all_exist = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path} (missing)")
            all_exist = False
    
    return all_exist


def check_output_dir():
    """Check if output directory exists."""
    print("\nChecking output directory...")
    
    if os.path.exists("out"):
        print("  ✓ ./out/ directory exists")
    else:
        print("  ℹ️  ./out/ will be created automatically")
    
    return True


def main():
    """Run all checks."""
    print("="*60)
    print("Claude DB Agent - Setup Verification")
    print("="*60 + "\n")
    
    checks = [
        check_package_structure(),
        check_dependencies(),
        check_env_file(),
        check_output_dir(),
    ]
    
    print("\n" + "="*60)
    
    if all(checks):
        print("✓ All checks passed! You're ready to use Claude DB Agent.")
        print("\nRun the agent with:")
        print("  python -m claude_db_agent")
        print("  or: python3 -m claude_db_agent")
        print("\n" + "="*60)
        return 0
    else:
        print("⚠️  Some checks failed. Please fix the issues above.")
        print("="*60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

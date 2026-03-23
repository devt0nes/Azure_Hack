"""
agent_examples.py - Working Examples for All Pre-configured Agents

This file demonstrates how to use each pre-configured agent role
with realistic examples.
"""

from general_agent import (
    GeneralAgent,
    BackendEngineerAgent,
    FrontendDeveloperAgent,
    DevOpsEngineerAgent
)


def example_1_backend_rest_api():
    """
    Example 1: Backend Engineer - Create REST API for a bakery
    """
    print("\n" + "="*70)
    print("EXAMPLE 1: Backend Engineer - Bakery REST API")
    print("="*70)
    
    agent = BackendEngineerAgent()
    
    result = agent.execute(
        task_description="""
Create a RESTFUL API for a bakery website with full CRUD functionality.

Requirements:
- Item management (create, read, update, delete items)
- Admin-only item modifications
- Display all items to public
- User authentication (register, login)
- Role-based access control (admin, user)
- Shopping cart functionality
- Checkout and purchase completion
- Database storage (sqlite for testing)
- Comprehensive tests
        """,
        context={
            "database": "sqlite",
            "framework": "express",
            "auth_method": "JWT",
        }
    )
    
    print("\n✅ Backend Agent Result:")
    print(result[:500])


def example_2_frontend_todo_app():
    """
    Example 2: Frontend Developer - Build React todo app
    """
    print("\n" + "="*70)
    print("EXAMPLE 2: Frontend Developer - React Todo App")
    print("="*70)
    
    agent = FrontendDeveloperAgent()
    
    result = agent.execute(
        task_description="""
Build a React todo application with the following features:

Requirements:
- Add new todos
- Mark todos as complete
- Delete todos
- Filter by status (all, active, completed)
- Persist todos to localStorage
- Responsive design (mobile, tablet, desktop)
- Accessibility (ARIA labels, keyboard navigation)
- Error handling
- Loading states
        """,
        context={
            "framework": "react",
            "styling": "tailwind",
            "state_management": "context-api",
        }
    )
    
    print("\n✅ Frontend Agent Result:")
    print(result[:500])


def example_3_devops_ci_cd():
    """
    Example 3: DevOps Engineer - Setup CI/CD pipeline
    """
    print("\n" + "="*70)
    print("EXAMPLE 3: DevOps Engineer - GitHub Actions CI/CD")
    print("="*70)
    
    agent = DevOpsEngineerAgent()
    
    result = agent.execute(
        task_description="""
Setup a complete CI/CD pipeline for a Node.js application using GitHub Actions:

Requirements:
- Trigger on push and pull requests
- Run linting (ESLint)
- Run unit tests
- Run integration tests
- Build Docker image
- Push image to Docker Hub
- Deploy to staging environment
- Run smoke tests
- Notify on success/failure
        """,
        context={
            "platform": "github",
            "language": "javascript",
            "cloud": "docker",
        }
    )
    
    print("\n✅ DevOps Agent Result:")
    print(result[:500])


def example_4_custom_data_engineer():
    """
    Example 4: Custom Role - Data Engineer with ETL pipeline
    """
    print("\n" + "="*70)
    print("EXAMPLE 4: Custom Role - Data Engineer ETL Pipeline")
    print("="*70)
    
    agent = GeneralAgent(
        role="Data Engineer",
        role_description="""
Build and maintain data pipelines and ETL processes.
Handle data extraction, transformation, loading, and quality assurance.
Work with multiple data sources and destinations.
Ensure data integrity and performance optimization.
        """,
        specific_instructions="""
⚠️ DATA ENGINEER SPECIFIC WORKFLOW:
1. Design data schema and transformations
2. Create source connectors (extraction)
3. Create transformation logic
4. Create destination connectors (loading)
5. Implement data validation rules
6. Setup error handling and retries
7. Create monitoring and alerting
8. Document data lineage
9. Write tests
10. Deploy and monitor

ALWAYS IMPLEMENT:
- Data quality checks
- Error recovery
- Logging and monitoring
- Schema versioning
- Data lineage documentation
- Performance optimization

DO NOT:
- Skip data validation
- Use production data for testing
- Hardcode source/destination info
- Leave failed pipelines unmonitored
        """,
        timeout=120
    )
    
    result = agent.execute(
        task_description="""
Create a daily ETL pipeline that:
- Extracts data from PostgreSQL database
- Transforms raw data (cleaning, aggregation, joins)
- Loads transformed data to Snowflake
- Generates data quality report
- Sends notifications on completion
        """,
        context={
            "source": "postgresql",
            "destination": "snowflake",
            "schedule": "daily",
            "orchestration": "airflow",
        }
    )
    
    print("\n✅ Data Engineer Result:")
    print(result[:500])


def example_5_custom_qa_engineer():
    """
    Example 5: Custom Role - QA Engineer with test automation
    """
    print("\n" + "="*70)
    print("EXAMPLE 5: Custom Role - QA Engineer Test Automation")
    print("="*70)
    
    agent = GeneralAgent(
        role="QA Engineer",
        role_description="""
Create comprehensive test suites and ensure code quality.
Handle unit tests, integration tests, and end-to-end tests.
Setup test automation and CI/CD integration.
Ensure quality gates and coverage requirements.
        """,
        specific_instructions="""
⚠️ QA ENGINEER SPECIFIC WORKFLOW:
1. Analyze requirements and create test plan
2. Create unit tests (>80% coverage)
3. Create integration tests
4. Create end-to-end tests
5. Setup test automation
6. Setup CI/CD integration
7. Create test reports
8. Monitor test trends

ALWAYS IMPLEMENT:
- Unit tests (80%+ coverage)
- Integration tests
- E2E tests for critical flows
- API contract tests
- Performance tests
- Security tests

DO NOT:
- Skip error paths
- Hardcode test data
- Leave tests flaky
- Skip regression tests
        """,
        timeout=90
    )
    
    result = agent.execute(
        task_description="""
Create comprehensive test suite for a REST API:
- Unit tests for controllers
- Integration tests for endpoints
- API contract tests
- Error handling tests
- Performance tests
        """,
        context={
            "framework": "jest",
            "language": "javascript",
            "coverage_target": "80%",
        }
    )
    
    print("\n✅ QA Engineer Result:")
    print(result[:500])


def example_6_custom_ml_engineer():
    """
    Example 6: Custom Role - ML Engineer with model pipeline
    """
    print("\n" + "="*70)
    print("EXAMPLE 6: Custom Role - ML Engineer Model Pipeline")
    print("="*70)
    
    agent = GeneralAgent(
        role="ML Engineer",
        role_description="""
Build and deploy machine learning models.
Handle data preprocessing, feature engineering, model training, and inference.
Manage model versioning and deployment pipelines.
Monitor model performance and retraining.
        """,
        specific_instructions="""
⚠️ ML ENGINEER SPECIFIC WORKFLOW:
1. Data exploration and analysis
2. Data preprocessing and cleaning
3. Feature engineering
4. Model selection and training
5. Hyperparameter tuning
6. Model evaluation
7. Model versioning
8. Create inference pipeline
9. Create monitoring
10. Deploy to production

ALWAYS IMPLEMENT:
- Data validation
- Feature scaling
- Train/test split
- Cross-validation
- Model versioning
- Inference pipeline
- Performance monitoring
- Retraining triggers

DO NOT:
- Train on full dataset
- Ignore data leakage
- Skip model validation
- Deploy without monitoring
        """,
        timeout=180
    )
    
    result = agent.execute(
        task_description="""
Build a machine learning pipeline for customer churn prediction:
- Load and explore customer data
- Preprocess and engineer features
- Train multiple models
- Evaluate and select best model
- Create inference pipeline
- Setup monitoring
        """,
        context={
            "framework": "sklearn",
            "language": "python",
            "dataset": "customer_data.csv",
        }
    )
    
    print("\n✅ ML Engineer Result:")
    print(result[:500])


def main():
    """
    Run examples - comment out any you don't want to run
    """
    
    # Backend Examples
    # example_1_backend_rest_api()
    
    # Frontend Examples
    # example_2_frontend_todo_app()
    
    # DevOps Examples
    # example_3_devops_ci_cd()
    
    # Data Engineering Examples
    # example_4_custom_data_engineer()
    
    # QA Engineering Examples
    # example_5_custom_qa_engineer()
    
    # ML Engineering Examples
    # example_6_custom_ml_engineer()
    
    # Run all examples
    print("\n" + "="*70)
    print("AGENT EXAMPLES - Uncomment examples in main() to run them")
    print("="*70)
    print("""
Available examples:
1. example_1_backend_rest_api() - Backend Engineer building REST API
2. example_2_frontend_todo_app() - Frontend Developer building React app
3. example_3_devops_ci_cd() - DevOps setting up CI/CD
4. example_4_custom_data_engineer() - Custom Data Engineer with ETL
5. example_5_custom_qa_engineer() - Custom QA Engineer with tests
6. example_6_custom_ml_engineer() - Custom ML Engineer with model pipeline

Each example demonstrates:
- How to create an agent for a specific role
- How to customize role description and workflow
- How to pass context and task description
- Expected output structure

To run an example, uncomment it in the main() function and run:
    python agent_examples.py
    """)


if __name__ == "__main__":
    main()

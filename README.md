# Insight Flow

<p align="center">

### AI-Powered Natural Language SQL Data Assistant

Transform Natural Language into Business Insights using Artificial Intelligence.

</p>

---

## Overview

Insight Flow is an AI-powered Business Intelligence platform that enables users to analyze business data using natural language instead of writing SQL queries.

Users can simply ask questions in plain English, and the platform automatically understands the request, generates optimized PostgreSQL queries, validates them for security, executes them against a PostgreSQL database, explains the results in business-friendly language, and recommends the most appropriate data visualization.

The project combines Artificial Intelligence, Large Language Models, Natural Language Processing, Business Intelligence, and modern web technologies to make data analytics accessible to both technical and non-technical users.

Unlike traditional Business Intelligence tools that require SQL knowledge, Insight Flow allows users to interact with data through conversation.

---

# Problem Statement

Organizations collect massive amounts of data every day, but extracting meaningful insights often requires technical expertise.

Business users, managers, students, and decision-makers frequently depend on developers or data analysts to answer questions such as:

- Which product category generated the highest revenue?
- Which age group spends the most money?
- What are the monthly sales trends?
- Which transactions exceeded a certain amount?
- Which customer segment performs best?

Answering these questions traditionally involves several manual steps:

- Understanding the database schema
- Writing SQL queries
- Validating query correctness
- Executing queries
- Exporting results
- Creating visualizations
- Interpreting the findings

This process is time-consuming and requires knowledge of SQL and database systems, creating a significant barrier for non-technical users.

---

# Why I Built This Project

The primary objective of Insight Flow was to eliminate the gap between business users and relational databases.

Instead of requiring users to learn SQL, the application allows them to ask questions naturally, just as they would ask another person.

For example, instead of writing:

```sql
SELECT
    product_category,
    SUM(total_amount)
FROM retail_sales
GROUP BY product_category
ORDER BY SUM(total_amount) DESC;
```

Users simply ask:

> Which product category generated the highest revenue?

The AI handles the entire analytical workflow automatically.

The project demonstrates how Generative AI can simplify Business Intelligence by combining Natural Language Processing, Large Language Models, secure SQL execution, and interactive data visualization into a single seamless experience.

---

# Solution

Insight Flow provides an end-to-end AI-powered analytics workflow.

The system accepts a natural language question and processes it through multiple intelligent layers before returning a final response.

The workflow includes:

- Understanding the user's question
- Generating PostgreSQL SQL queries using AI
- Validating generated SQL before execution
- Securely executing queries against PostgreSQL
- Retrieving database results
- Explaining results using AI
- Determining the best way to present the data
- Returning structured JSON to the frontend
- Rendering charts or tables dynamically

This approach allows users to interact with data naturally without needing any knowledge of SQL syntax or database structures.

---

# What Problem Does Insight Flow Solve?

Insight Flow removes the technical barrier between users and data.

Instead of spending time learning SQL or waiting for analysts to prepare reports, users can retrieve information instantly by asking questions in everyday language.

The platform automates the complete analytical workflow, significantly reducing the effort required to explore business data.

It transforms complex database interactions into a simple conversational experience.

---

# Use Cases

Insight Flow can be useful in many real-world scenarios.

### Retail Analytics

- Sales performance analysis
- Product category comparisons
- Revenue tracking
- Customer purchasing behavior
- Monthly sales reports
- Transaction filtering

---

### Business Intelligence

- Executive dashboards
- KPI monitoring
- Trend analysis
- Revenue analysis
- Customer segmentation
- Sales insights

---

### Educational Purpose

Students learning

- SQL
- Artificial Intelligence
- Business Intelligence
- FastAPI
- LangChain
- Prompt Engineering
- PostgreSQL

can use Insight Flow to understand how AI can automate SQL generation and data analytics.

---

### Decision Support

Business managers can quickly retrieve answers such as:

- Which products are performing best?
- Which customer group spends the most?
- Which months generated the highest sales?
- Which categories contribute the most revenue?
- What trends exist in customer purchases?

without writing SQL.

---

# Current Scope

This version of Insight Flow is designed specifically for the included Retail Sales dataset.

The AI assistant has been built and optimized to understand the schema, relationships, and business context of this dataset.

Users can ask questions related only to the provided retail sales data.

Examples include:

- Show monthly sales.
- Which age group spends the most money?
- List all Electronics transactions above $1000.
- What is the average purchase amount by gender?
- Which product category generated the highest revenue?

The assistant is not intended to answer questions about arbitrary datasets in the current version.

---

# Future Dataset Support

The long-term vision of Insight Flow is to become a general-purpose AI analytics platform.

Future versions will allow users to:

- Upload CSV files
- Upload Excel files
- Connect PostgreSQL databases
- Connect MySQL databases
- Automatically generate metadata
- Automatically profile uploaded datasets
- Dynamically understand new schemas
- Answer questions on any uploaded dataset without requiring code changes

This enhancement will transform Insight Flow from a dataset-specific assistant into a universal AI-powered Business Intelligence platform.

---

# Key Features

## Natural Language to SQL

Users ask questions in plain English.

The AI automatically generates optimized PostgreSQL queries without requiring any SQL knowledge.

---

## Secure SQL Validation

Every AI-generated SQL query is validated before execution.

Only safe read-only queries are allowed.

Potentially dangerous operations such as INSERT, UPDATE, DELETE, DROP, ALTER, and other destructive SQL statements are rejected before reaching the database.

---

## AI-Powered Business Explanation

Instead of displaying raw database results, Insight Flow generates clear business-friendly explanations.

This helps non-technical users understand insights without interpreting SQL query results manually.

---

## Intelligent Visualization Recommendation

After retrieving query results, the system analyzes both the user's analytical goal and the returned data to determine the most appropriate presentation.

Depending on the scenario, the application can recommend:

- Data Tables
- KPI Cards
- Bar Charts
- Line Charts
- Area Charts
- Pie Charts
- Scatter Charts

The frontend acts purely as a renderer, displaying exactly what the backend recommends.

---

## Conversation-Based Analytics

Users interact with the platform through a conversational chat interface, making data exploration feel natural and intuitive rather than technical.

---

## Secure Authentication

Insight Flow includes a complete authentication system powered by Supabase Authentication.

Features include:

- Email & Password Login
- Google Authentication
- Persistent Sessions
- Protected Routes
- Secure Logout
- Automatic Session Restoration

---

## Production Deployment

The application has been successfully deployed.

Frontend

- Vercel

Backend

- FastAPI deployed on Vercel

Database

- Supabase PostgreSQL

Authentication

- Supabase Authentication

The deployed application provides a complete end-to-end AI-powered analytics experience.

---

# System Architecture

Insight Flow follows a modular, AI-driven architecture where each layer has a single responsibility. Instead of relying on one large AI prompt, the application separates SQL generation, validation, execution, explanation, and visualization into independent modules.

This architecture makes the system easier to maintain, extend, and debug while ensuring every stage of the analytical pipeline is deterministic and secure.

```
                    User

                      │

                      ▼

         Natural Language Question

                      │

                      ▼

            Next.js Frontend (Chat UI)

                      │

                      ▼

          FastAPI REST API Endpoint

                      │

                      ▼

             Database Metadata Layer

                      │

                      ▼

         AI SQL Generator (Gemini + LangChain)

                      │

                      ▼

              SQL Validation Layer

                      │

                      ▼

             PostgreSQL SQL Executor

                      │

                      ▼

           Supabase PostgreSQL Database

                      │

                      ▼

               Query Result Dataset

                      │

                      ▼

         AI Business Result Explainer

                      │

                      ▼

        Analytical Goal Classification

                      │

                      ▼

      Visualization Planning Engine

                      │

                      ▼

     Standardized JSON API Response

                      │

                      ▼

          Next.js Visualization Layer

                      │

                      ▼

       Charts / Tables / KPI Components
```

---

# End-to-End Workflow

Every user request passes through multiple intelligent stages before reaching the frontend.

```
User asks a question

↓

FastAPI receives request

↓

Load database metadata

↓

Generate SQL using Gemini

↓

Validate generated SQL

↓

Execute SQL securely

↓

Retrieve database results

↓

Generate business explanation

↓

Determine analytical goal

↓

Plan best presentation

↓

Return standardized JSON

↓

Frontend renders answer

↓

User receives insights
```

Each stage performs one specific responsibility.

This separation makes the system scalable and easy to maintain.

---

# AI Pipeline

The AI pipeline combines deterministic backend logic with Generative AI.

Instead of allowing AI to control every decision, the application uses AI only where reasoning is required.

```
Natural Language

↓

Question Understanding

↓

Database Context

↓

Prompt Engineering

↓

Gemini AI

↓

SQL Generation

↓

SQL Validation

↓

Secure Execution

↓

Database Results

↓

Business Explanation

↓

Analytical Goal Detection

↓

Visualization Planning

↓

Frontend Rendering
```

---

# Backend Architecture

The backend is built using FastAPI and follows a modular architecture.

Each module performs a single task within the overall AI pipeline.

## Metadata Layer

The metadata layer provides database knowledge to the AI.

Responsibilities include:

- Reading database schema
- Loading table information
- Loading column names
- Identifying column data types
- Providing schema context to Gemini

This enables the AI to generate SQL using actual database information rather than assumptions.

---

## Database Profiling Layer

The profiling layer collects useful information about the dataset.

Examples include:

- Numeric columns
- Categorical columns
- Date columns
- Primary identifiers
- Value distributions
- Distinct counts

These insights help improve SQL generation and visualization planning.

---

## SQL Generation Engine

This module converts natural language into PostgreSQL queries.

Powered by:

- Google Gemini
- LangChain Prompt Templates

Responsibilities include:

- Understanding user intent
- Understanding schema
- Generating PostgreSQL SQL
- Producing optimized queries
- Supporting business-style questions

---

## SQL Validation Engine

AI-generated SQL is never executed directly.

Every query passes through a validation layer.

Validation includes:

- SQL syntax checking
- Read-only enforcement
- Dangerous keyword detection
- Table validation
- Column validation
- Query safety verification

Only safe SQL queries are executed.

---

## SQL Execution Engine

Responsible for:

- Connecting to Supabase PostgreSQL
- Executing validated SQL
- Returning structured results
- Measuring execution time
- Handling database errors
- Formatting response data

---

## AI Business Explanation

Database results are useful, but not always easy to interpret.

Insight Flow converts raw data into business-friendly explanations.

The explanation engine generates:

- Summary
- Key insights
- Trends
- Business observations
- Human-readable conclusions

This makes analytics accessible to non-technical users.

---

## Analytical Goal Detection

Instead of asking,

"What chart should be shown?"

the AI first determines,

"What is the user trying to accomplish?"

Examples include:

- List records
- Compare values
- Show trends
- Show composition
- Show ranking
- Show relationships
- Display KPIs

Understanding the analytical goal produces significantly better visualization decisions.

---

## Visualization Planning Engine

Once the analytical goal is known, the backend determines the best presentation.

Possible presentation types include:

- Table
- KPI Card
- Bar Chart
- Line Chart
- Area Chart
- Pie Chart
- Scatter Chart

The backend decides:

- Presentation type
- Chart type
- X-axis
- Y-axis
- Series
- Sorting
- Legend
- Orientation

The frontend simply renders the metadata returned by the backend.

---

# Standardized API Response

Every request returns a consistent JSON response.

```json
{
  "success": true,
  "question": "...",
  "sql": "...",
  "execution_time": 0.43,
  "row_count": 15,
  "data": [],
  "answer": "...",
  "visualization": {},
  "error": null
}
```

A standardized response ensures predictable frontend rendering and simplifies future maintenance.

---

# Frontend Architecture

The frontend is built with Next.js App Router and follows a component-based architecture.

Major responsibilities include:

- Authentication
- Dashboard
- Chat Interface
- API Communication
- Conversation Rendering
- Visualization Rendering
- Loading States
- Responsive Design

---

# Chat Experience

The application provides a conversational analytics experience.

Users can:

- Ask questions naturally
- Receive AI-generated responses
- View charts
- View tables
- Continue conversations
- Explore business insights interactively

This creates an experience similar to chatting with an AI business analyst.

---

# Visualization Rendering

The backend is the single source of truth for all visualization decisions.

The frontend never attempts to determine:

- Which chart to render
- Which axes to use
- Which series to display
- Whether a table is better than a chart

Instead, it simply renders the visualization metadata received from the backend.

This separation keeps business logic centralized and makes frontend components reusable.

Supported presentation components include:

- Data Tables
- KPI Cards
- Bar Charts
- Line Charts
- Area Charts
- Pie Charts
- Scatter Charts

---

# Authentication System

Authentication is implemented using Supabase Authentication.

Supported features include:

- Email & Password Login
- User Registration
- Google Sign-In
- Persistent Sessions
- Automatic Session Recovery
- Protected Routes
- Secure Logout
- Middleware Authentication

This ensures only authenticated users can access the analytics platform.

---

# Technology Stack

## Frontend

- Next.js (App Router)
- JavaScript (ES6+)
- Tailwind CSS
- shadcn/ui
- Recharts
- Framer Motion
- Lucide React

---

## Backend

- Python
- FastAPI
- Uvicorn
- LangChain

---

## Artificial Intelligence

- Google Gemini
- Prompt Engineering
- Natural Language Processing
- Large Language Models

---

## Database

- Supabase PostgreSQL

---

## Authentication

- Supabase Authentication
- Google OAuth
- Email Authentication

---

## Deployment

### Frontend

- Vercel

### Backend

- FastAPI deployed on Vercel

### Database

- Supabase PostgreSQL

### Authentication

- Supabase Authentication

---

# Why This Architecture?

Several architectural decisions were made during development to improve scalability and maintainability.

- Modular backend with single-responsibility components
- Secure SQL validation before execution
- AI used only for reasoning tasks
- Deterministic backend for execution and visualization planning
- Standardized JSON responses between backend and frontend
- Clear separation of business logic and UI rendering
- Component-based frontend architecture
- Production-ready deployment on Vercel
- Secure cloud-hosted PostgreSQL using Supabase

This design makes Insight Flow easier to extend with additional datasets, databases, visualization types, and AI capabilities in future versions.

/** Shared API types mirroring the FastAPI contracts. */

export interface ApiErrorBody {
  success: false;
  error: { code: string; message: string; details?: unknown };
}

export interface User {
  id: string;
  name: string;
  email: string;
  created_at?: string | null;
}

export interface DatabaseConnection {
  id: string;
  name: string;
  database_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  ssl_mode: string;
  has_password: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TestResult {
  success: boolean;
  message: string;
  server_version: string | null;
  latency_ms: number | null;
}

export interface SchemaColumn {
  name: string;
  type: string;
  udt?: string;
  nullable?: boolean;
  pk?: boolean;
}

export interface SchemaTable {
  schema: string;
  name: string;
  kind: 'table' | 'view';
  columns: SchemaColumn[];
}

export interface SchemaRelationship {
  schema: string;
  table: string;
  column: string;
  ref_schema: string;
  ref_table: string;
  ref_column: string;
}

export interface DatabaseSchema {
  success: boolean;
  schemas: string[];
  tables: SchemaTable[];
  relationships: SchemaRelationship[];
  fetched_at: number;
}

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  statement_type: string | null;
  tables: string[];
  functions: string[];
}

export interface GenerateResponse {
  success: boolean;
  sql: string | null;
  explanation: string;
  clarification: string | null;
  validation: ValidationReport | null;
  model: string;
  generation_time_ms: number;
  schema_tables: number;
  errors: string[];
  history_id: string;
}

export interface ResultColumn {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'datetime' | 'json' | string;
}

export interface ResultMetadata {
  row_count: number;
  returned_rows: number;
  execution_time_ms: number;
  truncated: boolean;
  response_bytes: number;
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'pie' | 'area' | 'table';
  x?: string;
  y?: string;
  available: boolean;
  reason: string;
}

export interface ExecuteResponse {
  success: boolean;
  columns: ResultColumn[];
  rows: (string | number | boolean | null)[][];
  metadata: ResultMetadata;
  chart: ChartSpec | null;
  history_id: string;
}

export interface HistoryItem {
  id: string;
  connection_id: string | null;
  conversation_id: string | null;
  question: string;
  generated_sql: string;
  execution_status: string;
  execution_time_ms: number | null;
  row_count: number | null;
  error_message: string | null;
  created_at: string;
}

export interface SavedQuery {
  id: string;
  connection_id: string | null;
  title: string;
  description: string | null;
  natural_language_question: string;
  sql_query: string;
  tags: string[];
  is_favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  connection_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  metadata: {
    kind?: 'sql' | 'clarification' | 'error';
    sql?: string;
    explanation?: string;
    validation?: ValidationReport | null;
    error?: string;
  } | null;
  created_at: string;
}

export interface AiHealth {
  status: string;
  provider: string;
  model: string;
  message: string;
  models: string[];
  latency_ms: number | null;
}

export interface OverviewStats {
  connections: number;
  total_queries: number;
  successful_queries: number;
  saved_queries: number;
  favorite_queries: number;
  avg_execution_time_ms: number | null;
}

export interface OverviewResponse {
  success: boolean;
  stats: OverviewStats;
  recent_activity: {
    id: string;
    question: string;
    status: string;
    row_count: number | null;
    execution_time_ms: number | null;
    created_at: string | null;
  }[];
}

export interface UserSettings {
  theme: 'light' | 'dark' | 'system';
  default_chart_type: 'auto' | 'bar' | 'line' | 'pie' | 'table';
  default_row_limit: number;
}

export interface Paged<T> {
  success: boolean;
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CsvPreview {
  success: boolean;
  columns: { name: string; type: string }[];
  row_count: number;
  preview_rows: (string | number | boolean | null)[][];
  suggested_table: string;
}

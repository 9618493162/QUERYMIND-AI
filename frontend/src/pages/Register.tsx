import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, Sparkles, UserPlus } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { Field, Input } from '../components/ui/primitives';
import { ApiError } from '../services/api';

const schema = z
  .object({
    name: z.string().min(1, 'Name is required').max(120),
    email: z.string().email('Enter a valid email address'),
    password: z.string().min(8, 'Password must be at least 8 characters').max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  });

type FormValues = z.infer<typeof schema>;

export default function Register() {
  const { register: registerUser } = useAuth();
  const { push } = useToast();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    try {
      await registerUser(values.name, values.email, values.password);
      push('Account created. Welcome to QueryMind AI!', 'success');
      navigate('/app', { replace: true });
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Registration failed. Please try again.');
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2 text-lg font-semibold">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          QueryMind AI
        </Link>
        <div className="card p-6">
          <h1 className="text-xl font-semibold">Create your account</h1>
          <p className="mt-1 text-sm text-slate-500">
            Start asking your databases questions in plain English.
          </p>

          {serverError && (
            <div
              className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-300"
              role="alert"
            >
              {serverError}
            </div>
          )}

          <form className="mt-5" onSubmit={handleSubmit(onSubmit)} noValidate>
            <Field label="Full name" error={errors.name?.message}>
              <Input
                placeholder="Jane Doe"
                autoComplete="name"
                invalid={!!errors.name}
                {...register('name')}
              />
            </Field>
            <Field label="Email" error={errors.email?.message}>
              <Input
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                invalid={!!errors.email}
                {...register('email')}
              />
            </Field>
            <Field
              label="Password"
              error={errors.password?.message}
              hint="At least 8 characters."
            >
              <Input
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                invalid={!!errors.password}
                {...register('password')}
              />
            </Field>
            <Field label="Confirm password" error={errors.confirm?.message}>
              <Input
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                invalid={!!errors.confirm}
                {...register('confirm')}
              />
            </Field>
            <button type="submit" className="btn-primary w-full" disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              Create account
            </button>
          </form>

          <p className="mt-4 text-center text-sm text-slate-500">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-brand-600 hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

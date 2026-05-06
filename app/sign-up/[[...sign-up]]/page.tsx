import { SignUp } from '@clerk/nextjs'
import AuthShell from '@/components/AuthShell'
import { clerkAppearance } from '@/lib/clerk-appearance'

export default function SignUpPage() {
  return (
    <AuthShell headingId="sign-up-heading">
      <h1 id="sign-up-heading" className="sr-only">
        Sign up
      </h1>
      <SignUp
        appearance={clerkAppearance}
        routing="path"
        path="/sign-up"
        signInUrl="/sign-in"
      />
    </AuthShell>
  )
}

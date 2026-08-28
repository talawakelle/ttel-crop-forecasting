# Practical operations protocol

## Before the morning plan

1. Confirm the crop target and active fields.
2. Confirm expected attendees under the normal division rule.
3. Count additional workers who are genuinely reachable and eligible today.
4. Set a transfer limit based on transport, receiving-supervisor capacity, and
   estate policy.

Do not enter the v0.9 best-case numbers unless those resources are truly
available that morning.

## What the software guarantees

The v1.0 optimizer enforces the entered additional-worker and transfer caps
inside CP-SAT. The exported plan cannot exceed either cap. It also checks one
assignment per employee, active fields, field capacity, and the zero-transfer
rule when the transfer limit is zero.

## What the supervisor must verify

- Every additional alias maps to the intended real employee and is present.
- Every transferred employee is eligible and has transport.
- Medical, leave, skill, legal-hours, and field-access restrictions are clear.
- The crop target is still valid at deployment time.

The confirmation checkboxes are local interface gates, not a secure electronic
signature or audit trail. Authentication, role-based approval, HR identity
mapping, and immutable audit logging should be added before production use.

## When the plan stays below 85%

Use the reported gap as a capacity signal. Do not lower the target or inflate
productivity to manufacture an 85% result. Escalate the shortage, adjust the
harvest programme operationally, or add verified workers/resources and rerun.

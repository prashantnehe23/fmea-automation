1. Think Before Coding

Example 1: Hidden Assumptions

User Request: "Add a feature to export user data"



❌ What LLMs Do (Wrong Assumptions)



def export\_users(format='json'):

&#x20;   """Export all users to a file."""

&#x20;   users = User.query.all()

&#x20;   

&#x20;   if format == 'json':

&#x20;       with open('users.json', 'w') as f:

&#x20;           json.dump(\[u.to\_dict() for u in users], f)

&#x20;   elif format == 'csv':

&#x20;       with open('users.csv', 'w') as f:

&#x20;           writer = csv.DictWriter(f, fieldnames=\['id', 'email', 'name'])

&#x20;           writer.writeheader()

&#x20;           writer.writerows(\[u.to\_dict() for u in users])

&#x20;   

&#x20;   return f"Exported {len(users)} users"

Problems:



Assumed it should export ALL users (what about pagination? privacy?)

Assumed file location without asking

Assumed which fields to include

Assumed CSV fieldnames without checking actual data structure

✅ What Should Happen (Surface Assumptions)



Before implementing, I need to clarify:



1\. \*\*Scope\*\*: Export all users or filtered subset? (privacy implications)

2\. \*\*Format\*\*: You mentioned "export" - did you mean:

&#x20;  - Download file in browser?

&#x20;  - Background job with email notification?

&#x20;  - API endpoint returning data?

3\. \*\*Fields\*\*: Which user fields? (some might be sensitive)

4\. \*\*Volume\*\*: How many users typically? (affects approach)



Simplest approach: Add an API endpoint that returns paginated JSON.

Would need more info for file-based exports.



What's your preference?

Example 2: Multiple Interpretations

User Request: "Make the search faster"



❌ What LLMs Do (Pick Silently)



\# Adds caching, database indexes, and async processing

\# without asking which "faster" matters

@lru\_cache(maxsize=1000)

async def search(query: str) -> List\[Result]:

&#x20;   # ... 200 lines of optimization code

✅ What Should Happen



"Make the search faster" could mean:



1\. \*\*Faster response time\*\* (< 100ms instead of 500ms)

&#x20;  - Add database indexes

&#x20;  - Cache frequent queries

&#x20;  - Estimated effort: 2 hours



2\. \*\*Handle more concurrent searches\*\* (throughput)

&#x20;  - Add async/await

&#x20;  - Connection pooling

&#x20;  - Estimated effort: 4 hours



3\. \*\*Faster perceived speed\*\* (UX)

&#x20;  - Show partial results immediately

&#x20;  - Progressive loading

&#x20;  - Estimated effort: 3 hours



Current search takes \~500ms for typical queries. 

Which aspect matters most for your use case?

2\. Simplicity First

Example 1: Over-abstraction

User Request: "Add a function to calculate discount"



❌ What LLMs Do (Overengineered)



from abc import ABC, abstractmethod

from enum import Enum

from typing import Protocol, Union

from dataclasses import dataclass



class DiscountStrategy(ABC):

&#x20;   @abstractmethod

&#x20;   def calculate(self, amount: float) -> float:

&#x20;       pass



class PercentageDiscount(DiscountStrategy):

&#x20;   def \_\_init\_\_(self, percentage: float):

&#x20;       self.percentage = percentage

&#x20;   

&#x20;   def calculate(self, amount: float) -> float:

&#x20;       return amount \* (self.percentage / 100)



class FixedDiscount(DiscountStrategy):

&#x20;   def \_\_init\_\_(self, fixed\_amount: float):

&#x20;       self.fixed\_amount = fixed\_amount

&#x20;   

&#x20;   def calculate(self, amount: float) -> float:

&#x20;       return min(self.fixed\_amount, amount)



@dataclass

class DiscountConfig:

&#x20;   strategy: DiscountStrategy

&#x20;   min\_purchase: float = 0.0

&#x20;   max\_discount: float = float('inf')



class DiscountCalculator:

&#x20;   def \_\_init\_\_(self, config: DiscountConfig):

&#x20;       self.config = config

&#x20;   

&#x20;   def apply\_discount(self, amount: float) -> float:

&#x20;       if amount < self.config.min\_purchase:

&#x20;           return 0

&#x20;       discount = self.config.strategy.calculate(amount)

&#x20;       return min(discount, self.config.max\_discount)



\# Usage requires 30+ lines of setup for a simple calculation

✅ What Should Happen (Simple)



def calculate\_discount(amount: float, percent: float) -> float:

&#x20;   """Calculate discount amount. percent should be 0-100."""

&#x20;   return amount \* (percent / 100)



\# Usage

discount = calculate\_discount(100.0, 10.0)  # $10 off

When to add complexity: Only when you actually need multiple discount types. If that requirement comes later, refactor then.



Example 2: Speculative Features

User Request: "Save user preferences to database"



❌ What LLMs Do (Unnecessary Features)



class PreferenceManager:

&#x20;   def \_\_init\_\_(self, db, cache=None, validator=None):

&#x20;       self.db = db

&#x20;       self.cache = cache or InMemoryCache()

&#x20;       self.validator = validator or DefaultValidator()

&#x20;   

&#x20;   def save(self, user\_id: int, prefs: dict, 

&#x20;            merge: bool = True, 

&#x20;            validate: bool = True,

&#x20;            notify: bool = False) -> bool:

&#x20;       """Save preferences with optional merging, validation, and notifications."""

&#x20;       

&#x20;       if validate:

&#x20;           errors = self.validator.validate(prefs)

&#x20;           if errors:

&#x20;               raise ValidationError(errors)

&#x20;       

&#x20;       existing = self.get(user\_id) if merge else {}

&#x20;       

&#x20;       if merge:

&#x20;           existing.update(prefs)

&#x20;           prefs = existing

&#x20;       

&#x20;       self.db.execute(

&#x20;           "UPDATE users SET preferences = ? WHERE id = ?",

&#x20;           (json.dumps(prefs), user\_id)

&#x20;       )

&#x20;       

&#x20;       if self.cache:

&#x20;           self.cache.set(f"prefs:{user\_id}", prefs)

&#x20;       

&#x20;       if notify:

&#x20;           self.notify\_preference\_change(user\_id, prefs)

&#x20;       

&#x20;       return True

&#x20;   

&#x20;   def notify\_preference\_change(self, user\_id: int, prefs: dict):

&#x20;       # Another 30 lines for a feature nobody asked for

&#x20;       pass

✅ What Should Happen (Just What Was Asked)



def save\_preferences(db, user\_id: int, preferences: dict):

&#x20;   """Save user preferences to database."""

&#x20;   db.execute(

&#x20;       "UPDATE users SET preferences = ? WHERE id = ?",

&#x20;       (json.dumps(preferences), user\_id)

&#x20;   )

Add later if needed: Caching (when performance matters), validation (when bad data appears), merging (when requirement emerges).



3\. Surgical Changes

Example 1: Drive-by Refactoring

User Request: "Fix the bug where empty emails crash the validator"



❌ What LLMs Do (Too Much)



&#x20; def validate\_user(user\_data):

\-     # Check email format

\-     if not user\_data.get('email'):

\+     """Validate user data."""

\+     email = user\_data.get('email', '').strip()

\+     

\+     # Validate email

\+     if not email:

&#x20;         raise ValueError("Email required")

\-     

\-     # Basic email validation

\-     if '@' not in user\_data\['email']:

\+     if '@' not in email or '.' not in email.split('@')\[1]:

&#x20;         raise ValueError("Invalid email")

&#x20;     

\-     # Check username

\-     if not user\_data.get('username'):

\+     # Validate username

\+     username = user\_data.get('username', '').strip()

\+     if not username:

&#x20;         raise ValueError("Username required")

\+     if len(username) < 3:

\+         raise ValueError("Username too short")

\+     if not username.isalnum():

\+         raise ValueError("Username must be alphanumeric")

&#x20;     

&#x20;     return True

Problems:



"Improved" email validation beyond the bug fix

Added username validation nobody asked for

Changed comments

Added docstring

✅ What Should Happen (Surgical)



&#x20; def validate\_user(user\_data):

&#x20;     # Check email format

\-     if not user\_data.get('email'):

\+     email = user\_data.get('email', '')

\+     if not email or not email.strip():

&#x20;         raise ValueError("Email required")

&#x20;     

&#x20;     # Basic email validation

\-     if '@' not in user\_data\['email']:

\+     if '@' not in email:

&#x20;         raise ValueError("Invalid email")

&#x20;     

&#x20;     # Check username

&#x20;     if not user\_data.get('username'):

&#x20;         raise ValueError("Username required")

&#x20;     

&#x20;     return True

Only changed: The specific lines that fix empty email handling.



Example 2: Style Drift

User Request: "Add logging to the upload function"



❌ What LLMs Do (Reformat Everything)



\- def upload\_file(file\_path, destination):

\+ def upload\_file(file\_path: str, destination: str) -> bool:

\+     """Upload file to destination with logging."""

\+     logger.info(f"Uploading {file\_path} to {destination}")

\+     

&#x20;     try:

\-         with open(file\_path, 'rb') as f:

\-             data = f.read()

\-         

\-         response = requests.post(destination, files={'file': data})

\-         

\-         if response.status\_code == 200:

\-             return True

\-         else:

\-             return False

\+         with open(file\_path, "rb") as f:

\+             data = f.read()

\+         response = requests.post(destination, files={"file": data})

\+         success = response.status\_code == 200

\+         

\+         if success:

\+             logger.info(f"Upload successful: {file\_path}")

\+         else:

\+             logger.error(f"Upload failed: {file\_path}, status={response.status\_code}")

\+         

\+         return success

&#x20;     except Exception as e:

\-         print(f"Error: {e}")

\+         logger.exception(f"Upload error for {file\_path}: {e}")

&#x20;         return False

Problems:



Changed quote style ('' to "")

Added type hints nobody asked for

Added docstring

Reformatted whitespace

Changed boolean return logic

✅ What Should Happen (Match Existing Style)



\+ import logging

\+ 

\+ logger = logging.getLogger(\_\_name\_\_)

\+ 

&#x20; def upload\_file(file\_path, destination):

\+     logger.info(f'Starting upload: {file\_path}')

&#x20;     try:

&#x20;         with open(file\_path, 'rb') as f:

&#x20;             data = f.read()

&#x20;         

&#x20;         response = requests.post(destination, files={'file': data})

&#x20;         

&#x20;         if response.status\_code == 200:

\+             logger.info(f'Upload successful: {file\_path}')

&#x20;             return True

&#x20;         else:

\+             logger.error(f'Upload failed: {file\_path}, status={response.status\_code}')

&#x20;             return False

&#x20;     except Exception as e:

\-         print(f"Error: {e}")

\+         logger.exception(f'Upload error: {file\_path}')

&#x20;         return False

Matched: Single quotes, no type hints, existing boolean pattern, spacing style.



4\. Goal-Driven Execution

Example 1: Vague vs. Verifiable

User Request: "Fix the authentication system"



❌ What LLMs Do (Vague Approach)



I'll fix the authentication system by:

1\. Reviewing the code

2\. Identifying issues

3\. Making improvements

4\. Testing the changes



\[Proceeds to make changes without clear success criteria]

✅ What Should Happen (Verifiable Goals)



To "fix authentication," I need to define success criteria. 

What specific issue are we solving?



If the issue is "users stay logged in after password change":



Plan:

1\. Write test: Change password → verify old session invalidated

&#x20;  Verify: Test fails (reproduces bug)



2\. Implement: Invalidate sessions on password change

&#x20;  Verify: Test passes



3\. Check edge cases: Multiple active sessions, concurrent changes

&#x20;  Verify: Additional tests pass



4\. Verify no regression: Existing auth tests still pass

&#x20;  Verify: Full test suite green



Current test coverage for auth: \[shows coverage]

What's the specific auth issue you're seeing?

Example 2: Multi-Step with Verification

User Request: "Add rate limiting to the API"



❌ What LLMs Do (All at Once)



\# Implements full rate limiting with Redis, multiple strategies,

\# configuration system, and monitoring in one 300-line commit

\# No clear verification steps

✅ What Should Happen (Incremental with Verification)



Plan for rate limiting:



1\. Add basic in-memory rate limiting (single endpoint)

&#x20;  Verify: 

&#x20;  - Test: 100 requests → first 10 succeed, rest get 429

&#x20;  - Manual: curl endpoint 11 times, see rate limit error



2\. Extract to middleware (apply to all endpoints)

&#x20;  Verify:

&#x20;  - Test: Rate limits apply to /users and /posts

&#x20;  - Existing endpoint tests still pass



3\. Add Redis backend (for multi-server)

&#x20;  Verify:

&#x20;  - Test: Rate limit persists across app restarts

&#x20;  - Test: Two app instances share rate limit counter



4\. Add configuration (rates per endpoint)

&#x20;  Verify:

&#x20;  - Test: /search allows 10/min, /users allows 100/min

&#x20;  - Config file parsed correctly



Each step is independently verifiable and deployable.

Start with step 1?

Example 3: Test-First Verification

User Request: "The sorting breaks when there are duplicate scores"



❌ What LLMs Do (Fix Without Reproducing)



\# Immediately changes sort logic without confirming the bug

def sort\_scores(scores):

&#x20;   return sorted(scores, key=lambda x: (-x\['score'], x\['name']))

✅ What Should Happen (Reproduce First)



\# 1. First, write a test that reproduces the issue

def test\_sort\_with\_duplicate\_scores():

&#x20;   """Test sorting when multiple items have same score."""

&#x20;   scores = \[

&#x20;       {'name': 'Alice', 'score': 100},

&#x20;       {'name': 'Bob', 'score': 100},

&#x20;       {'name': 'Charlie', 'score': 90},

&#x20;   ]

&#x20;   

&#x20;   result = sort\_scores(scores)

&#x20;   

&#x20;   # The bug: order is non-deterministic for duplicates

&#x20;   # Run this test multiple times, it should be consistent

&#x20;   assert result\[0]\['score'] == 100

&#x20;   assert result\[1]\['score'] == 100

&#x20;   assert result\[2]\['score'] == 90



\# Verify: Run test 10 times → fails with inconsistent ordering



\# 2. Now fix with stable sort

def sort\_scores(scores):

&#x20;   """Sort by score descending, then name ascending for ties."""

&#x20;   return sorted(scores, key=lambda x: (-x\['score'], x\['name']))



\# Verify: Test passes consistently

Anti-Patterns Summary

Principle	Anti-Pattern	Fix

Think Before Coding	Silently assumes file format, fields, scope	List assumptions explicitly, ask for clarification

Simplicity First	Strategy pattern for single discount calculation	One function until complexity is actually needed

Surgical Changes	Reformats quotes, adds type hints while fixing bug	Only change lines that fix the reported issue

Goal-Driven	"I'll review and improve the code"	"Write test for bug X → make it pass → verify no regressions"

Key Insight

The "overcomplicated" examples aren't obviously wrong—they follow design patterns and best practices. The problem is timing: they add complexity before it's needed, which:



Makes code harder to understand

Introduces more bugs

Takes longer to implement

Harder to test

The "simple" versions are:



Easier to understand

Faster to implement

Easier to test

Can be refactored later when complexity is actually needed

Good code is code that solves today's problem simply, not tomorrow's problem prematurely.


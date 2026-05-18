minimost.database
=================

.. automodule:: minimost.database
   :members:
   :undoc-members: False
   :show-inheritance:

.. note::

   :func:`minimost.database.init_auth_db` is called automatically at module
   import time. It is not necessary to call it manually.

auth.db Schema
--------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Column
     - Type
     - Description
   * - ``username``
     - TEXT PK
     - Unique account identifier. Validated against
       ``[A-Za-z0-9_\\-]{1,32}`` on registration.
   * - ``password_hash``
     - TEXT NOT NULL
     - PBKDF2 hash produced by Werkzeug. Never stored in plaintext.

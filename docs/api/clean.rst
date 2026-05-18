minimost.clean
==============

.. automodule:: minimost.clean
   :members:
   :undoc-members: False
   :show-inheritance:

Usage
-----

**As a cron job** (recommended — delete uploads older than 30 days at 02:30
every day):

.. code-block:: bash

    30 2 * * * /usr/bin/python3 /srv/minimost/src/minimost/clean.py

**From the command line:**

.. code-block:: bash

    python3 src/minimost/clean.py

**Programmatically:**

.. code-block:: python

    from minimost.clean import delete_files_older_than

    # Preview what would be deleted (no files removed)
    delete_files_older_than("uploads", days=30, dry_run=True)

    # Delete files older than 14 days
    delete_files_older_than("uploads", days=14)

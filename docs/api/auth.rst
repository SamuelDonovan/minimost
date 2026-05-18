minimost.auth
=============

.. automodule:: minimost.auth
   :members:
   :undoc-members: False
   :show-inheritance:

Route Summary
-------------

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Method
     - Path
     - Handler
   * - GET, POST
     - ``/login``, ``/login.html``
     - :func:`minimost.auth.login`
   * - GET
     - ``/logout``
     - :func:`minimost.auth.logout`
   * - GET, POST
     - ``/signup``
     - :func:`minimost.auth.signup`

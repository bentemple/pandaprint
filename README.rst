============
 PandaPrint
============

This is a server that enables uploading from OrcaSlicer to Bambu Lab
printers in LAN mode without the use of the Bambu Lab network plugin.

Users concerned about security or software freedom may be reluctant to
use either the Bambu Lab cloud service or the proprietary Bambu Lab
network plugin.  PandaPrint does not replace all of the functionality
in the network plugin, but it does allow sending a project to a
printer directly from OrcaSlicer.

Configuration
=============

Create a ``printers.yaml`` file like this example:

.. code-block:: yaml

   printers:
     - name: bambu
       host: bambu.lan
       serial: 123456789012345
       key: 12345678

The fields are as follows:

**name**: A friendly name of your choosing.  This will appear in the
 url supplied to OrcaSlicer later.  If you have more than one printer,
 ensure this is unique.

**host**: The hostname or IP address of the printer.

**serial**: The serial number of the printer.

**key**: The access key for the printer.  Get this from the LAN mode
 screen.

Running
=======

The easiest way to run this is from a container image.

Running the Container Image
---------------------------

A sample docker-compose file is included.

.. code-block:: shell

   docker compose up -d

Running from Source
-------------------

To run this directly from the source repo:

.. code-block:: shell

   poetry install
   poetry run pandaprint ./printers.yaml

Configuring OrcaSlicer
======================

1. Edit the printer.
2. Enable the `Advanced` toggle.
3. Under `Basic information`, `Advanced`, check ``Use 3rd-party print host``
4. Close the printer edit dialog.
5. Click the `Connection` button (wifi icon) next to the printer.
6. Under `Print Host uplod` set the following:
   **Host Type**: ``Octo/Klipper``
   **Hostname, IP or URL**: ``http://localhost:8080/bambu``  (if you chose something other than ``bambu`` as the name in ``printers.yaml``, use that here instead)
7. Press the `Test` button to ensure everything is working.
8. Press "OK"

At this point, you should be able to use the `Print Plate` button to send projects to the printer.

License
=======

This software is licensed under the AGPLv3.  See ``LICENSE.txt`` for details.

Contributing
============

Pull requests are welcome.

Running Tests
-------------

.. code-block:: shell

   cd tools
   ./test-setup.sh
   cd ..
   poetry run stestr init
   poetry run stestr run

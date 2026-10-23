{# Armed only with an enabled supplicant, as in wan8021x_enabled(). #}
{% set armed = [] %}
{% if helpers.exists('OPNsense.Wan8021x.general.enabled') and OPNsense.Wan8021x.general.enabled == '1' %}
{%   for entry in helpers.toList('OPNsense.Wan8021x.supplicants.supplicant') %}
{%     if entry.enabled|default('0') == '1' %}
{%       do armed.append(entry.interface) %}
{%     endif %}
{%   endfor %}
{% endif %}
{% if armed %}
wan8021x_enable="YES"
{% else %}
wan8021x_enable="NO"
{% endif %}

// This function allows any page to switch between content tabs in
// the Bootstrap framework. It is generally called upon loading the page.
function switch_tab(element)
{
	element.preventDefault();
	$(this).tab('show')
}

function set_tool_link_callback(callback)
{
	$("#tool_tree").find("a[data-type='tool link']").each(function()
	{
		$(this).click({"callback": callback}, callback);
	});
}

// This function allows categories in the tool tree sidebar to be expanded and collapsed.
// It must be called upon loading any page that uses the tool tree.
function enable_tool_tree_toggling()
{
	$('label.tree-toggler').click(toggle_branch);
}

// This function toggles a tool category branch for the sidebar in the calendar & tool control pages.
function toggle_branch()
{
	$(this).parent().children('ul.tree').toggle(300, save_sidebar_state);
}

function on_tool_search_selection(jquery_event, search_selection, dataset_name)
{
	$('#tool_search').typeahead('val', '');
	expand_to_tool(search_selection.id);
}

// This function toggles all parent categories of a tool and selects the tool.
function expand_to_tool(id)
{
	$("#sidebar a").removeClass('selected');
	//$("a[data-tool-id='" + id + "']").addClass('selected').click().parents('ul.tree').show();
	$("#tool_tree").find("a[data-tool-id='" + id + "']").addClass('selected').click().parents('ul.tree').show();
	//save_sidebar_state();
}

// This function expands all tool category branches for the sidebar in the calendar & tool control pages.
function expand_all_categories()
{
	$("#tool_tree ul.tree").show();
	$("#search").focus();
	save_sidebar_state();
}

// This function collapses all tool category branches for the sidebar in the calendar & tool control pages.
function collapse_all_categories()
{
	$("#tool_tree ul.tree").hide();
	$("#search").focus();
	save_sidebar_state();
}

function get_selected_item()
{
	let selected_item = $("#tool_tree").find(".selected");
	// Exactly one thing should be selected at a time, otherwise there's an error.
	if(!(selected_item && selected_item.length === 1))
		selected_item = $("#sidebar .selected");
	// Check if the selected item is a special link. Otherwise, get its tool ID.
	if($(selected_item[0]).hasClass('personal_schedule'))
		return 'personal_schedule';
	return $(selected_item[0]).data('tool-id');
}

// This function visually highlights a clicked link with a gray background.
function set_selected_item(element)
{
	if ($("#calendar").length)
	{
		$("#calendar").fullCalendar("removeEvents");
	}
	$("#sidebar a").removeClass('selected');
	$(element).addClass('selected');
	$("#current_tool_selection").html($(element).text());
	save_sidebar_state();
}

function set_selected_item_by_id(tool_id)
{
	if (!tool_id) {
		tool_id = 1;
	}
	let tool = $("#tool_tree [data-tool-id=" + tool_id + "]");
	if(tool.length === 1)
	{
		$("#sidebar a").removeClass('selected');
		tool.addClass('selected');
		$("#current_tool_selection").html(tool.text());
	}
}

function save_sidebar_state()
{
	localStorage.clear();
	let categories = $("#tool_tree ul.tree");
	for(let c = 0; c < categories.length; c++)
	{
		let category = categories[c].getAttribute('data-category');
		localStorage[category] = $(categories[c]).is(':visible');
	}
	localStorage['Selected tool ID'] = get_selected_item();
}

function load_sidebar_state()
{
	let categories = $("#tool_tree ul.tree");
	for(let c = 0; c < categories.length; c++)
	{
		let category = categories[c];
		let name = category.getAttribute('data-category');
		let state = localStorage[name];
		if(state === "true")
			$(category).show();
		else
			$(category).hide();
	}
	let selected = localStorage['Selected tool ID'];
	if(selected)
		set_selected_item_by_id(selected);
}

function refresh_sidebar_icons()
{
	$.getScript('/refresh_sidebar_icons/');
}

// Use this function to display a Bootstrap modal when an AJAX call is successful and contains content to render.
// Use this function with ajax_get(), ajax_post() or other similar functions.
function ajax_success_callback(response, status, xml_http_request)
{
	if(response)
	{
		$("#dialog .modal-content").html(response);
		$("#dialog").modal('show');
	}
}

// This function returns a callback. Upon AJAX message failure, the
// callback displays the error message in a Bootstrap modal dialog.
// Use this function with ajax_get(), ajax_post() or other similar functions.
function ajax_failure_callback(title, preface)
{
	preface = preface || "";
	function callback(xml_http_request, status, exception)
	{
		let dialog_contents =
			"<div class='modal-header'>" +
			"<button type='button' class='close' data-dismiss='modal'>&times;</button>" +
			"<h4 class='modal-title'>" + title + "</h4>" +
			"</div>" +
			"<div class='modal-body'>" +
			[preface, xml_http_request.responseText].join(" ") +
			"</div>";
		$("#dialog .modal-content").html(dialog_contents);
		$("#dialog").modal('show');
	}

	return callback;
}

function ajax_complete_callback(title, preface)
{
	preface = preface || "";
	function callback(response, status, xml_header_request)
	{
		if(status !== "error")
			return;
		let dialog_contents =
			"<div class='modal-header'>" +
			"<button type='button' class='close' data-dismiss='modal'>&times;</button>" +
			"<h4 class='modal-title'>" + title + "</h4>" +
			"</div>" +
			"<div class='modal-body'>" +
			[preface, xml_header_request.responseText].join(" ") +
			"</div>";
		$("#dialog .modal-content").html(dialog_contents);
		$("#dialog").modal('show');
	}

	return callback;
}

// Take all the elements in a form and put them in a JavaScript object.
function serialize(form_selector, ajax_message)
{
	if(ajax_message === undefined)
		ajax_message = {};
	let form_values = $(form_selector).serializeArray();
	for(let c = 0; c < form_values.length; c++)
		ajax_message[form_values[c].name] = form_values[c].value;
	return ajax_message;
}

function ajax_get(url, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	ajax_message(url, "GET", contents, success_callback, failure_callback, always_callback, traditional_serialization)
}

function ajax_post(url, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	if(contents === undefined)
		contents = {};
	//noinspection JSUnresolvedFunction
	contents.csrfmiddlewaretoken = csrf_token();
	ajax_message(url, "POST", contents, success_callback, failure_callback, always_callback, traditional_serialization)
}

function ajax_message(url, type, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	let options =
	{
		"data": contents,
		"type": type,
		"traditional": traditional_serialization === true
	};
	let message = jQuery.ajax(url, options);
	if(success_callback !== undefined)
		message.done(success_callback);
	if(failure_callback !== undefined)
		message.fail(failure_callback);
	if(always_callback !== undefined)
		message.always(always_callback);
}

function reload_page(response, status, xml_http_request)
{
	location.reload(true);
}

//noinspection JSUnusedGlobalSymbols
function on_change_configuration(configuration_id, slot, choice)
{
	let reconfiguration_properties =
	{
		"configuration_id": configuration_id,
		"slot": slot,
		"choice": choice
	};
	let failure_dialog = ajax_failure_callback("Configuration change failed", "There was a problem while changing this tool's configuration.");
	ajax_post('/tool_configuration/', reconfiguration_properties, undefined, failure_dialog);
}

function autofocus(selector)
{
	$("#dialog").one('shown.bs.modal', function()
	{
		$(selector).focus();
	});
}

function toggle_details(element)
{
	$(element).children('.chevron').toggleClass('glyphicon-chevron-right glyphicon-chevron-down', 200);
	return false;
}

function add_to_list(list_selector, on_click, id, text, removal_title, input_name, no_delete=false)
{
	let div_id = input_name + "_" + id;
	let div_id_selector = "#" + div_id;
	let addition = '<div id="' + div_id + '">';
	if (!no_delete) {
		addition += '<a href="javascript:' + on_click + '(' + id + ')" class="grey hover-black" title="' + removal_title + '">';
		addition += '<span class="glyphicon glyphicon-remove-circle"></span>';
		addition += '</a> ';
	}
	addition += text;
	addition += '<input type="hidden" name="' + input_name + '" value="' + id + '"><br>';
	addition += '</div>';
	if($(list_selector).find('input').length === 0) // If the list is empty then replace the empty message with the list item.
		$(list_selector).html(addition);
	else if($(div_id_selector).length === 0) // Only add the element if it's not already in the list.
		$(list_selector).append(addition);
}

function remove_from_list(list_selector, div_id_selector, emptyMessage)
{
	$(list_selector + " > " + div_id_selector).remove();
	if($(list_selector).find('input').length === 0) // If the list is empty then replace it with the empty message.
		$(list_selector).html(emptyMessage);
}

// From http://twitter.github.io/typeahead.js/examples/
function matcher(items, search_fields)
{
	return function find_matches(query, callback)
	{
		// An array that will be populated with substring matches
		let matches = [];

		// Regular expression used to determine if a string contains the substring `query`
		let matching_regular_expression = new RegExp(query, 'i');

		// Iterate through the pool of strings and for any string that
		// contains the substring `query`, add it to the `matches` array
		$.each(items, function(item_index, item)
		{
			$.each(search_fields, function(search_field_index, search_term)
			{
				if(search_term in item && matching_regular_expression.test(item[search_term]))
				{
					// The typeahead jQuery plugin expects suggestions to a
					// JavaScript object, refer to typeahead docs for more info
					matches.push(item);
				}
			});
		});

		callback(matches);
	};
}

// This jQuery plugin integrates Twitter Typeahead directly with default parameters & search function.
//
// Example usage:
// function on_select(jquery_event, search_selection, dataset_name)
// {
//     ... called when an item is selected ...
// }
// $('#search').autocomplete('fruits', on_select, [{name:'apple', id:1}, {name:'banana', id:2}, {name:'cherry', id:3}]);
(function($)
{
	$.fn.autocomplete = function(dataset_name, select_callback, items_to_search)
	{
		let search_fields = ['name', 'application_identifier', 'owner', 'organization', 'username', 'email', 'project_number'];
		let datasets =
		{
				source: matcher(items_to_search, search_fields),
				name: dataset_name,
				displayKey: 'name'
		};
		datasets['templates'] =
		{
			'suggestion': function(data)
			{
				let result = data['name'];
				//if(data['type'])
				//	result += '<br><span style="font-size:small; font-weight:bold; color:#bbbbbb">' + data['type'] + '</span>';
				if(data['application_identifier'])
					result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['application_identifier'] + '</span>';

				if(data['owner'])
					result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['owner'] + '</span>';

				//if(data['organization'])
				//	result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['organization'] + '</span>';
				//if(data['username']) 
				//	result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['username'] + '</span>';
				if(data['email'])
					result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['email'] + '</span>';

				if(data['project_number']) {
					sPN = data['project_number'];
					sPN = sPN.substring(0,49);
					result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + sPN + '</span>';
				}

				return result;
			}
		};
		this.typeahead(
			{
				minLength: 1,
				hint: false,
				highlight: false
			},
			datasets
		);
		this.bind('typeahead:selected', select_callback);
		return this;
	};
}(jQuery));

// This function will limit the allowed input characters for the 
// indicated field whether entered by keypress or pasting
(function($)
{
	$.fn.limitInputCharacters = function(allowedCharacters) {
		this.on('input', function(event) {
			let currentValue = $(this).val();
			let sanitizedValue = '';
    
			for (let i = 0; i < currentValue.length; i++) {
				let currentCharacter = currentValue.charAt(i);
      
				if (allowedCharacters.indexOf(currentCharacter) !== -1) {
					sanitizedValue += currentCharacter;
				}
			}
    
			$(this).val(sanitizedValue);
		});
	};
}(jQuery));
// instantiating some default allowed character strings
var INTEGERS_ONLY = "0123456789";
var NUMBERS_ONLY = ".0123456789";
var LETTERS_ONLY = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
var LETTERS_AND_NUMBERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
var GENERAL_EDITING = LETTERS_AND_NUMBERS + ".'-_+=?,!@#$%^&*();:" + '"';


// HTTP error 403 (unauthorized) is returned when the user's session
// has timed out and the web page makes an AJAX request. This 403 response
// is generated by the custom Django middleware called SessionTimeout.
// This function is registered as a global callback for AJAX completions
// in /templates/base.html so that when error 403 is returned the browser
// is redirected to the logout page, and then further redirected to the login
// page. This design is useful because some of NEMO's pages (such as the
// Calendar, Tool Control, and Status Dashboard) make regular polling AJAX requests.
function navigate_to_login_on_session_expiration(event, xhr, status, error)
{
	if(xhr.status === 403)
		window.location.href = '/logout/';
}

function convert_12_to_24(dDate)
{
	if (dDate == undefined) return;

	var arrDate = dDate.split(" ");
	var dayDate = arrDate[0];
	var arrTime = arrDate[1].split(":");
	var hr = parseInt(arrTime[0]);

	if (arrDate[2] == "PM") {
		if (hr < 12) {
			hr = hr + 12;
			hr = hr.toString();
		}
	} else {
		if (hr == 12) hr = "00";
	}
	arrDate[1] = hr + ":" + arrTime[1];
	var retDate = dayDate + " " + arrDate[1] + ":00";
	return retDate;
}

function calculate_duration()
{
	var start = null;
	var end = null;
	if ($("#ad_hoc_start").val() != "") {
		start = moment($("#ad_hoc_start").val());
	}
	if ($("#ad_hoc_end").val() != "") {
		end = moment($("#ad_hoc_end").val());
	}
	if (start != null && end != null) {
		s_duration = "";
		duration = end.diff(start, 'hours', true);

		if (duration != parseInt(duration)) {
			s_duration = parseInt(duration) + " hours ";
			start = start.add(parseInt(duration), 'hour');
			duration = end.diff(start, 'minutes');
			s_duration += duration + " minutes";
		} else {
			s_duration = parseInt(duration) + " hours";
		}

		$("#duration").html(s_duration);
	}
}


function pair_selects(s1, s2)
{
	// a function to link two multiselect list to transfer their options back and forth
	s1_id = $(s1).prop("id");
	s2_id = $(s2).prop("id");

	s1_options_tag = "#" + s1_id + " > option";
	s2_options_tag = "#" + s2_id + " > option";

	s1_options = $(s1_options_tag);
	s2_options = $(s2_options_tag);

	s1_selected = "#" + s1_id + " > option:selected";
	s2_selected = "#" + s2_id + " > option:selected";

	s1.on("click", function () {
		$("option:selected", this).each(function () {
			$(s2).append($("<option></option>").attr("value",$(this).prop("value")).text($(this).text()));
			$(this).remove();
		});
		sort_options(this);
		sort_options(s2);
	});

	s2.on("click", function () {
		$("option:selected", this).each(function () {
			$(s1).append($("<option></option>").attr("value",$(this).prop("value")).text($(this).text()));
			$(this).remove();
		});
		sort_options(this);
		sort_options(s1);
	});
}

function sort_options(sel)
{
	var options = $("option", sel);
	var arr = options.map(function(_, o) { return { t: $(o).text(), v: o.value }; }).get();
	arr.sort(function(o1, o2) { return o1.t.toLowerCase() > o2.t.toLowerCase() ? 1 : o1.t.toLowerCase() < o2.t.toLowerCase() ? -1 : 0; });
	options.each(function(i, o) {
		o.value = arr[i].v;
		$(o).text(arr[i].t);
	});
}

function toggle_tool_watching(tool_id, user_id)
{
	if (isNaN(tool_id) || isNaN(user_id)) return false;

	var params = {
		"tool_id": tool_id,
		"user_id": user_id
	}

	var url = "/toggle_tool_watching/";

	ajax_post(url, params, [refresh_sidebar_icons], undefined);
}

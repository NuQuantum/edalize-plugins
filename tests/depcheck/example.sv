module example (
    input logic clk,
    input logic rst,
    input logic d,
    output logic [1:0] q
);

    example_dep u_example_dep (
        .clk,
        .rst,
        .d,
        .q
    );

endmodule
